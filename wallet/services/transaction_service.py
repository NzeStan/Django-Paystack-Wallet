"""
Transaction queries, statistics, refunds to card and reversals.

* :meth:`TransactionService.refund_deposit` sends money from a funded wallet
  back to the card/bank that paid it (Paystack Refunds API). The wallet is
  debited immediately; ``refund.failed`` puts it back.
* :meth:`TransactionService.reverse_transaction` undoes an internal movement
  (transfer or payment) - a staff/admin operation.
"""
import logging
from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.constants import (
    DIRECTION_CREDIT,
    DIRECTION_DEBIT,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_PROCESSING,
    TRANSACTION_STATUS_REVERSED,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUSES,
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_REFUND,
    TRANSACTION_TYPE_REVERSAL,
    TRANSACTION_TYPES,
    TRANSACTION_TYPE_WITHDRAWAL,
)
from wallet.exceptions import InvalidAmount, InvalidTransactionState, PaystackAPIError
from wallet.models import Transaction
from wallet.services.base import BaseService
from wallet.signals import (
    refund_completed,
    refund_failed,
    refund_initiated,
    send_on_commit,
    transaction_reversed,
)
from wallet.utils.id_generators import generate_refund_reference
from wallet.utils.money import to_decimal, to_minor_units

logger = logging.getLogger('wallet')

REFUND_ACTIVE_STATUSES = (TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING, TRANSACTION_STATUS_SUCCESS)


class TransactionService(BaseService):

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_transaction(self, transaction_id, for_update=False):
        queryset = Transaction.objects.select_related('wallet')
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.get(pk=transaction_id)

    def get_transaction_by_reference(self, reference, for_update=False):
        queryset = Transaction.objects.select_related('wallet')
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.get(reference=reference)

    def list_transactions(self, wallet=None, status=None, transaction_type=None, direction=None, start_date=None,
                          end_date=None, min_amount=None, max_amount=None, search=None):
        queryset = Transaction.objects.with_full_details()
        if wallet is not None:
            queryset = queryset.filter(wallet=wallet)
        if status:
            queryset = queryset.filter(status=status)
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        if direction:
            queryset = queryset.filter(direction=direction)
        queryset = queryset.in_date_range(start_date, end_date).by_amount_range(min_amount, max_amount)
        if search:
            queryset = queryset.filter(Q(reference__icontains=search) | Q(description__icontains=search))
        return queryset.order_by('-created_at')

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_transaction_statistics(self, wallet=None, start_date=None, end_date=None):
        queryset = Transaction.objects.all()
        if wallet is not None:
            queryset = queryset.filter(wallet=wallet)
        queryset = queryset.in_date_range(start_date, end_date)
        stats = queryset.statistics()
        stats = {key: (value if value is not None else Decimal('0')) for key, value in stats.items()}
        stats['by_type'] = {
            txn_type: queryset.filter(transaction_type=txn_type, status=TRANSACTION_STATUS_SUCCESS).count()
            for txn_type, _label in TRANSACTION_TYPES
        }
        return stats

    def get_transaction_summary(self, wallet=None, start_date=None, end_date=None):
        queryset = Transaction.objects.all()
        if wallet is not None:
            queryset = queryset.filter(wallet=wallet)
        queryset = queryset.in_date_range(start_date, end_date)
        success = queryset.filter(status=TRANSACTION_STATUS_SUCCESS)

        def total(qs, field='total_amount'):
            return qs.aggregate(total=Sum(field))['total'] or Decimal('0')

        return {
            'by_type': {
                txn_type: {
                    'display': str(label),
                    'count': queryset.filter(transaction_type=txn_type).count(),
                    'total_amount': total(success.filter(transaction_type=txn_type)),
                } for txn_type, label in TRANSACTION_TYPES
            },
            'by_status': {
                status: {
                    'display': str(label),
                    'count': queryset.filter(status=status).count(),
                    'total_amount': total(queryset.filter(status=status)),
                } for status, label in TRANSACTION_STATUSES
            },
            'overview': {
                'total_transactions': queryset.count(),
                'total_credits': total(success.filter(direction=DIRECTION_CREDIT)),
                'total_debits': total(success.filter(direction=DIRECTION_DEBIT)),
                'total_fees': total(success, 'fees'),
            },
        }

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_transaction(self, transaction, reason=None, performed_by=None):
        """Cancel an unpaid deposit or an escrowed payment."""
        if not transaction.can_be_cancelled():
            raise InvalidTransactionState(_("This transaction cannot be cancelled"))
        if transaction.transaction_type == TRANSACTION_TYPE_DEPOSIT:
            from wallet.services.deposit_service import DepositService
            return DepositService(paystack=self.paystack).cancel_deposit(transaction, reason, performed_by)
        from wallet.services.transfer_service import TransferService
        return TransferService(paystack=self.paystack).cancel_payment(transaction, reason, performed_by)

    # ------------------------------------------------------------------
    # Refunds to card (Paystack Refunds API)
    # ------------------------------------------------------------------

    def refundable_amount(self, transaction):
        refunded = Transaction.objects.filter(
            related_transaction=transaction, transaction_type=TRANSACTION_TYPE_REFUND,
            status__in=REFUND_ACTIVE_STATUSES,
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        return max(transaction.total_amount.amount - refunded, Decimal('0'))

    def refund_deposit(self, transaction, amount=None, reason=None, customer_note=None, merchant_note=None,
                       performed_by=None):
        """
        Refund (part of) a deposit back to the payer's card/bank account.

        The wallet is debited now; the refund transaction completes on the
        ``refund.processed`` webhook and is put back on ``refund.failed``.
        """
        self.require_feature('CARD_REFUNDS')
        if not transaction.can_be_refunded():
            raise InvalidTransactionState(_("Only successful Paystack deposits can be refunded"))

        refundable = self.refundable_amount(transaction)
        value = to_decimal(amount) if amount is not None else refundable
        if value <= 0:
            raise InvalidAmount(message=_("Nothing left to refund"))
        if value > refundable:
            raise InvalidAmount(message=_("You can refund at most {amount}").format(amount=refundable))
        refund_money = Money(value, transaction.amount.currency)

        with db_transaction.atomic():
            original = self.lock_transaction(transaction)
            wallet = original.wallet
            new_balance = wallet.debit(refund_money, enforce_minimum_balance=False, force=True)
            refund = Transaction.objects.create(
                wallet=wallet, amount=refund_money, total_amount=refund_money, balance_after=new_balance,
                transaction_type=TRANSACTION_TYPE_REFUND, direction=DIRECTION_DEBIT,
                status=TRANSACTION_STATUS_PENDING, reference=generate_refund_reference(),
                related_transaction=original, payment_method=original.payment_method,
                description=reason or str(_("Refund of {reference}").format(reference=original.reference)),
                metadata={'reason': reason or '', 'original_reference': original.reference,
                          **self.actor(performed_by)},
            )
        self.audit('refund.create', performed_by, transaction=original.reference, refund=refund.reference,
                   amount=value, reason=reason or '')

        try:
            data = self.paystack.refunds.create(
                transaction=transaction.paystack_reference or transaction.reference,
                amount=to_minor_units(value), currency=transaction.amount.currency.code,
                customer_note=customer_note, merchant_note=merchant_note or reason,
            )
        except PaystackAPIError as exc:
            if exc.is_definitive:
                self._fail_refund(refund, exc.paystack_message or exc.message)
                raise
            logger.warning("Refund %s outcome unknown: %s", refund.reference, exc)
            refund.metadata = {**refund.metadata, 'needs_reconciliation': True}
            refund.save(update_fields=['metadata', 'updated_at'])
            return refund

        refund.paystack_id = data.get('id')
        refund.paystack_response = data
        refund.save(update_fields=['paystack_id', 'paystack_response', 'updated_at'])
        send_on_commit(refund_initiated, sender=Transaction, transaction=refund, wallet=refund.wallet,
                       original_transaction=transaction)
        if (data.get('status') or '').lower() == 'processed':
            refund = self._complete_refund(refund, data)
        return refund

    # Backwards compatible name
    def refund_transaction(self, transaction, amount=None, refund_fees=True, reason=None):
        return self.refund_deposit(transaction, amount=amount, reason=reason)

    def process_refund_event(self, event, data, webhook_event=None):
        """Handle ``refund.pending`` / ``refund.processing`` / ``refund.processed`` / ``refund.failed``."""
        refund = self._find_refund(data)
        if refund is None:
            logger.info("Refund event %s could not be matched", event)
            return None
        if webhook_event is not None and webhook_event.transaction_id is None:
            webhook_event.transaction = refund
            webhook_event.save(update_fields=['transaction'])
        status = event.split('.', 1)[1]
        if status == 'processed':
            return self._complete_refund(refund, data)
        if status == 'failed':
            return self._fail_refund(refund, data.get('message') or str(_("Refund failed")), data)
        refund.paystack_response = data
        if data.get('id') and not refund.paystack_id:
            refund.paystack_id = data['id']
        refund.save(update_fields=['paystack_response', 'paystack_id', 'updated_at'])
        if refund.status == TRANSACTION_STATUS_PENDING and status == 'processing':
            self.set_status(refund, TRANSACTION_STATUS_PROCESSING)
        return refund

    def _complete_refund(self, refund, data=None):
        with db_transaction.atomic():
            refund = self.lock_transaction(refund)
            if refund.is_final:
                return refund
            if data:
                refund.paystack_response = data
                refund.save(update_fields=['paystack_response', 'updated_at'])
            self.set_status(refund, TRANSACTION_STATUS_SUCCESS)
            send_on_commit(refund_completed, sender=Transaction, transaction=refund, wallet=refund.wallet,
                           original_transaction=refund.related_transaction)
        return refund

    def _fail_refund(self, refund, reason, data=None):
        with db_transaction.atomic():
            refund = self.lock_transaction(refund)
            if refund.is_final:
                return refund
            new_balance = refund.wallet.credit(refund.total_amount, force=True)
            Transaction.objects.create(
                wallet=refund.wallet, amount=refund.total_amount, total_amount=refund.total_amount,
                balance_after=new_balance, transaction_type=TRANSACTION_TYPE_REVERSAL, direction=DIRECTION_CREDIT,
                status=TRANSACTION_STATUS_SUCCESS, completed_at=timezone.now(), reference=f"{refund.reference}-rev",
                related_transaction=refund,
                description=str(_("Failed refund {reference} returned to wallet").format(reference=refund.reference)),
                metadata={'reason': str(reason)},
            )
            if data:
                refund.paystack_response = data
                refund.save(update_fields=['paystack_response', 'updated_at'])
            self.set_status(refund, TRANSACTION_STATUS_FAILED, reason=reason)
            send_on_commit(refund_failed, sender=Transaction, transaction=refund, wallet=refund.wallet,
                           original_transaction=refund.related_transaction, reason=str(reason))
        return refund

    @staticmethod
    def _find_refund(data):
        queryset = Transaction.objects.filter(transaction_type=TRANSACTION_TYPE_REFUND)
        refund_id = data.get('id') or data.get('refund_id')
        if refund_id:
            match = queryset.filter(paystack_id=refund_id).first()
            if match:
                return match
        reference = data.get('transaction_reference')
        if not reference and isinstance(data.get('transaction'), dict):
            reference = data['transaction'].get('reference')
        if reference:
            return queryset.filter(
                related_transaction__reference=reference, status__in=(TRANSACTION_STATUS_PENDING,
                                                                      TRANSACTION_STATUS_PROCESSING),
            ).order_by('created_at').first()
        return None

    # ------------------------------------------------------------------
    # Reversals of internal movements
    # ------------------------------------------------------------------

    def reverse_transaction(self, transaction, reason=None, performed_by=None):
        """
        Undo a successful transfer or payment: the receiver is debited and the
        payer credited. Raises InsufficientFunds if the receiver already spent it.
        """
        if not transaction.can_be_reversed():
            raise InvalidTransactionState(_("Only successful outgoing transfers and payments can be reversed"))
        reason = reason or str(_("Reversed"))

        with db_transaction.atomic():
            debit_leg = self.lock_transaction(transaction)
            if not debit_leg.can_be_reversed():
                raise InvalidTransactionState(_("Transaction already reversed"))
            credit_leg = debit_leg.related_transaction
            payer = debit_leg.wallet
            now = timezone.now()

            if credit_leg is not None and credit_leg.is_successful and credit_leg.is_credit:
                credit_leg = self.lock_transaction(credit_leg)
                receiver = credit_leg.wallet
                receiver_balance = receiver.debit(credit_leg.total_amount, enforce_minimum_balance=False, force=True)
                Transaction.objects.create(
                    wallet=receiver, counterparty_wallet=payer, amount=credit_leg.total_amount,
                    total_amount=credit_leg.total_amount, balance_after=receiver_balance,
                    transaction_type=TRANSACTION_TYPE_REVERSAL, direction=DIRECTION_DEBIT,
                    status=TRANSACTION_STATUS_SUCCESS, completed_at=now, reference=f"{credit_leg.reference}-rev",
                    related_transaction=credit_leg, description=reason,
                )
                self.set_status(credit_leg, TRANSACTION_STATUS_REVERSED, reason=reason)

            payer_balance = payer.credit(debit_leg.total_amount, force=True)
            reversal = Transaction.objects.create(
                wallet=payer, counterparty_wallet=debit_leg.counterparty_wallet, amount=debit_leg.total_amount,
                total_amount=debit_leg.total_amount, balance_after=payer_balance,
                transaction_type=TRANSACTION_TYPE_REVERSAL, direction=DIRECTION_CREDIT,
                status=TRANSACTION_STATUS_SUCCESS, completed_at=now, reference=f"{debit_leg.reference}-rev",
                related_transaction=debit_leg, description=reason, metadata=self.actor(performed_by),
            )
            self.set_status(debit_leg, TRANSACTION_STATUS_REVERSED, reason=reason)
        self.audit('transaction.reverse', performed_by, transaction=debit_leg.reference, reason=reason)

        send_on_commit(transaction_reversed, sender=Transaction, transaction=reversal, wallet=payer,
                       original_transaction=debit_leg)
        return reversal

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(self, older_than_minutes=None):
        """Verify stale pending deposits and withdrawals with Paystack."""
        from wallet.services.deposit_service import DepositService
        from wallet.services.withdrawal_service import WithdrawalService

        return {
            'deposits': DepositService(paystack=self.paystack).reconcile_pending_deposits(older_than_minutes),
            'withdrawals': WithdrawalService(paystack=self.paystack).reconcile_pending_withdrawals(
                older_than_minutes
            ),
        }

    @staticmethod
    def pending_withdrawals():
        return Transaction.objects.filter(
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status__in=[TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING],
        )

    @staticmethod
    def escrowed_payments(wallet=None):
        queryset = Transaction.objects.filter(
            transaction_type=TRANSACTION_TYPE_PAYMENT, direction=DIRECTION_DEBIT,
            status=TRANSACTION_STATUS_PENDING, metadata__escrow=True,
        )
        return queryset.filter(Q(wallet=wallet) | Q(counterparty_wallet=wallet)) if wallet is not None else queryset
