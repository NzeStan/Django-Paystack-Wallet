"""
Settlements (payouts) and settlement schedules.

A settlement is a withdrawal with payout bookkeeping on top: it reuses
:class:`~wallet.services.withdrawal_service.WithdrawalService`, so it gets the
same money-safety guarantees (debit first, automatic reversal on failure).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.constants import (
    SETTLEMENT_STATUS_FAILED,
    SETTLEMENT_STATUS_PENDING,
    SETTLEMENT_STATUS_PROCESSING,
    SETTLEMENT_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_REVERSED,
    TRANSACTION_STATUS_SUCCESS,
)
from wallet.exceptions import InsufficientFunds, SettlementError, WalletError
from wallet.models import Settlement, SettlementSchedule
from wallet.services.base import BaseService
from wallet.signals import send_on_commit, settlement_completed, settlement_failed

logger = logging.getLogger('wallet')


class SettlementService(BaseService):

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_settlement(self, settlement_id):
        return Settlement.objects.with_full_details().get(pk=settlement_id)

    def get_settlement_by_reference(self, reference):
        return Settlement.objects.with_full_details().get(reference=reference)

    def get_settlements_for_wallet(self, wallet, status=None, limit=100):
        queryset = Settlement.objects.by_wallet(wallet).with_full_details()
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset[:limit])

    # ------------------------------------------------------------------
    # Creation & processing
    # ------------------------------------------------------------------

    def create_settlement(self, wallet, bank_account, amount, reason=None, metadata=None, schedule=None,
                          fee_bearer=None, auto_process=True):
        """Create a settlement and (by default) start the bank transfer immediately."""
        self.require_feature('SETTLEMENTS')
        if isinstance(amount, Money):
            amount_money = amount
        else:
            amount_money = Money(Decimal(str(amount)), wallet.currency)
        if amount_money.amount <= 0:
            raise SettlementError(_("Amount must be greater than zero"))
        if bank_account is None or bank_account.wallet_id != wallet.pk:
            raise SettlementError(_("Bank account does not belong to this wallet"))

        settlement = Settlement.objects.create(
            wallet=wallet, bank_account=bank_account, amount=amount_money, status=SETTLEMENT_STATUS_PENDING,
            reason=reason or str(_("Settlement to bank account")), metadata=metadata or {}, schedule=schedule,
        )
        if auto_process:
            return self.process_settlement(settlement, fee_bearer=fee_bearer)
        return settlement

    def process_settlement(self, settlement, fee_bearer=None):
        """Start the bank transfer for a pending (or failed, when retrying) settlement."""
        from wallet.services.withdrawal_service import WithdrawalService

        if settlement.status not in (SETTLEMENT_STATUS_PENDING, SETTLEMENT_STATUS_FAILED):
            raise SettlementError(_("Only pending settlements can be processed"))
        if settlement.transaction_id and settlement.status == SETTLEMENT_STATUS_PENDING:
            raise SettlementError(_("This settlement is already being processed"))

        try:
            txn, data = WithdrawalService(paystack=self.paystack).withdraw_to_bank(
                wallet=settlement.wallet, amount=settlement.amount, bank_account=settlement.bank_account,
                reason=settlement.reason, fee_bearer=fee_bearer,
                metadata={'settlement_id': str(settlement.pk), 'settlement_reference': settlement.reference},
            )
        except WalletError as exc:
            settlement.mark_as_failed(exc.message)
            send_on_commit(settlement_failed, sender=Settlement, settlement=settlement, wallet=settlement.wallet,
                           reason=exc.message)
            raise SettlementError(exc.message) from exc

        settlement.transaction = txn
        settlement.fees = txn.fees
        settlement.failure_reason = ''
        settlement.paystack_transfer_code = txn.paystack_transfer_code
        settlement.paystack_transfer_data = data
        settlement.save()
        self.sync_from_transaction(txn)
        settlement.refresh_from_db()
        return settlement

    def finalize_settlement(self, settlement, otp):
        from wallet.services.withdrawal_service import WithdrawalService

        if not settlement.transaction_id:
            raise SettlementError(_("Settlement has no transfer to finalize"))
        WithdrawalService(paystack=self.paystack).finalize_withdrawal(settlement.transaction, otp)
        settlement.refresh_from_db()
        return settlement

    def verify_settlement(self, settlement):
        from wallet.services.withdrawal_service import WithdrawalService

        if not settlement.transaction_id:
            raise SettlementError(_("Settlement has no transfer to verify"))
        WithdrawalService(paystack=self.paystack).verify_withdrawal(settlement.transaction)
        settlement.refresh_from_db()
        return settlement

    def retry_settlement(self, settlement):
        if settlement.status != SETTLEMENT_STATUS_FAILED:
            raise SettlementError(_("Only failed settlements can be retried"))
        if settlement.wallet.balance.amount < settlement.amount.amount:
            raise InsufficientFunds(settlement.wallet, settlement.amount)
        settlement.transaction = None
        settlement.save(update_fields=['transaction', 'updated_at'])
        return self.process_settlement(settlement)

    @staticmethod
    def sync_from_transaction(txn):
        """Mirror a withdrawal transaction's state onto its settlement (if any)."""
        settlement = Settlement.objects.filter(transaction_id=txn.pk).first()
        if settlement is None:
            return None
        previous = settlement.status
        settlement.paystack_transfer_code = txn.paystack_transfer_code or settlement.paystack_transfer_code
        if txn.status == TRANSACTION_STATUS_SUCCESS:
            settlement.status = SETTLEMENT_STATUS_SUCCESS
            settlement.settled_at = settlement.settled_at or timezone.now()
        elif txn.status in (TRANSACTION_STATUS_FAILED, TRANSACTION_STATUS_REVERSED):
            settlement.status = SETTLEMENT_STATUS_FAILED
            settlement.failure_reason = txn.failed_reason
        elif txn.requires_otp:
            settlement.status = SETTLEMENT_STATUS_PENDING
        else:
            settlement.status = SETTLEMENT_STATUS_PROCESSING
        settlement.paystack_transfer_data = txn.paystack_response or settlement.paystack_transfer_data
        settlement.save()

        if previous != settlement.status:
            if settlement.status == SETTLEMENT_STATUS_SUCCESS:
                send_on_commit(settlement_completed, sender=Settlement, settlement=settlement,
                               wallet=settlement.wallet)
            elif settlement.status == SETTLEMENT_STATUS_FAILED:
                send_on_commit(settlement_failed, sender=Settlement, settlement=settlement,
                               wallet=settlement.wallet, reason=settlement.failure_reason)
        return settlement

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    def create_settlement_schedule(self, wallet, bank_account, schedule_type, amount_threshold=None,
                                   minimum_amount=None, maximum_amount=None, day_of_week=None, day_of_month=None,
                                   time_of_day=None):
        self.require_feature('SETTLEMENTS')
        if bank_account.wallet_id != wallet.pk:
            raise SettlementError(_("Bank account does not belong to this wallet"))

        def as_money(value):
            if value is None or isinstance(value, Money):
                return value
            return Money(Decimal(str(value)), wallet.currency)

        schedule = SettlementSchedule(
            wallet=wallet, bank_account=bank_account, schedule_type=schedule_type,
            amount_threshold=as_money(amount_threshold),
            minimum_amount=as_money(minimum_amount) or Money(0, wallet.currency),
            maximum_amount=as_money(maximum_amount), day_of_week=day_of_week, day_of_month=day_of_month,
            time_of_day=time_of_day,
        )
        schedule.full_clean(exclude=['wallet', 'bank_account'])
        schedule.save()
        return schedule

    def calculate_settlement_amount(self, schedule):
        """How much a schedule should pay out right now (Money; zero means nothing)."""
        wallet = schedule.wallet
        wallet.refresh_balance()
        balance = wallet.balance.amount
        from wallet.conf import wallet_settings
        available = balance - Decimal(str(wallet_settings.MINIMUM_BALANCE or 0))

        if schedule.is_threshold_based:
            threshold = schedule.amount_threshold.amount if schedule.amount_threshold else None
            amount = balance - threshold if threshold is not None and balance > threshold else Decimal('0')
        else:
            amount = available
        amount = min(amount, available)
        if schedule.maximum_amount is not None:
            amount = min(amount, schedule.maximum_amount.amount)
        if amount <= 0 or amount < schedule.minimum_amount.amount:
            amount = Decimal('0')
        return Money(amount, wallet.currency)

    # Old private name
    _calculate_settlement_amount = calculate_settlement_amount

    def _run_schedule(self, schedule, reason):
        amount = self.calculate_settlement_amount(schedule)
        if amount.amount <= 0:
            return None
        return self.create_settlement(
            wallet=schedule.wallet, bank_account=schedule.bank_account, amount=amount, reason=reason,
            schedule=schedule, metadata={'schedule_id': str(schedule.pk), 'schedule_type': schedule.schedule_type},
        )

    def process_due_settlements(self):
        """Run every time-based schedule that is due. Returns the number of settlements created."""
        count = 0
        for schedule in SettlementSchedule.objects.due_now().with_full_details():
            try:
                if self._run_schedule(schedule, f"Scheduled {schedule.get_schedule_type_display()} settlement"):
                    count += 1
            except WalletError as exc:
                logger.warning("Scheduled settlement %s failed: %s", schedule.pk, exc)
            finally:
                schedule.last_settlement = timezone.now()
                schedule.next_settlement = schedule.compute_next_settlement()
                schedule.save(update_fields=['last_settlement', 'next_settlement', 'updated_at'])
        return count

    def process_threshold_schedules(self, wallet):
        """Pay out whatever is above each active threshold schedule of ``wallet``."""
        count = 0
        for schedule in SettlementSchedule.objects.threshold_based().filter(wallet=wallet).with_full_details():
            try:
                if self._run_schedule(schedule, str(_("Automatic threshold settlement"))):
                    schedule.last_settlement = timezone.now()
                    schedule.save(update_fields=['last_settlement', 'updated_at'])
                    count += 1
            except WalletError as exc:
                logger.warning("Threshold settlement %s failed: %s", schedule.pk, exc)
        return count

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_settlement_stats(self, wallet=None, start_date=None, end_date=None):
        queryset = Settlement.objects.all()
        if wallet is not None:
            queryset = queryset.by_wallet(wallet)
        queryset = queryset.in_date_range(start_date, end_date)
        stats = queryset.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            average_amount=Avg('amount'),
            successful_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_SUCCESS)),
            failed_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_FAILED)),
            pending_count=Count('id', filter=Q(status__in=[SETTLEMENT_STATUS_PENDING, SETTLEMENT_STATUS_PROCESSING])),
        )
        stats['total_amount'] = stats['total_amount'] or Decimal('0')
        stats['average_amount'] = stats['average_amount'] or Decimal('0')
        stats['success_rate'] = (
            round(stats['successful_count'] / stats['total_count'] * 100, 2) if stats['total_count'] else 0
        )
        return stats

    def get_settlement_summary(self, wallet, period_days=30):
        start = timezone.now() - timedelta(days=period_days)
        summary = Settlement.objects.by_wallet(wallet).in_date_range(start_date=start).aggregate(
            total_settled=Sum('amount', filter=Q(status=SETTLEMENT_STATUS_SUCCESS)),
            settlement_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_SUCCESS)),
            pending_count=Count('id', filter=Q(status__in=[SETTLEMENT_STATUS_PENDING, SETTLEMENT_STATUS_PROCESSING])),
            failed_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_FAILED)),
        )
        summary['total_settled'] = summary['total_settled'] or Decimal('0')
        summary.update({'period_days': period_days, 'period_start': start, 'period_end': timezone.now()})
        return summary

    def get_top_settlement_destinations(self, wallet, limit=5):
        return list(
            Settlement.objects.by_wallet(wallet).successful().values(
                'bank_account__id', 'bank_account__account_name', 'bank_account__account_number',
                'bank_account__bank__name',
            ).annotate(settlement_count=Count('id'), total_amount=Sum('amount')).order_by('-total_amount')[:limit]
        )
