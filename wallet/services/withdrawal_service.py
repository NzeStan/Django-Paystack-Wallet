"""
Withdrawals from a wallet to a bank account (Paystack Transfers).

Money safety rules:

1. The wallet is debited *before* Paystack is called, inside the same database
   transaction that records the withdrawal. The user can never spend the same
   money twice while a transfer is in flight.
2. If Paystack definitively rejects the transfer (4xx), the debit is reversed
   immediately.
3. If the outcome is unknown (timeout, 5xx), nothing is reversed - the
   transfer may have gone through. The transaction stays pending and is settled
   by the ``transfer.*`` webhook or by :meth:`reconcile_pending_withdrawals`.
4. ``transfer.failed`` / ``transfer.reversed`` webhooks put the money back,
   exactly once.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.conf import wallet_settings
from wallet.constants import (
    DIRECTION_CREDIT,
    DIRECTION_DEBIT,
    PAYMENT_METHOD_BANK_TRANSFER,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_PROCESSING,
    TRANSACTION_STATUS_REVERSED,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_TYPE_REVERSAL,
    TRANSACTION_TYPE_WITHDRAWAL,
)
from wallet.exceptions import BankAccountError, DuplicateReference, InvalidTransactionState, PaystackAPIError
from wallet.models import Transaction
from wallet.services.bank_account_service import BankAccountService
from wallet.services.base import BaseService
from wallet.services.fee_service import get_fee_calculator
from wallet.signals import send_on_commit, withdrawal_completed, withdrawal_failed, withdrawal_initiated
from wallet.utils.id_generators import generate_transfer_reference
from wallet.utils.money import to_minor_units

logger = logging.getLogger('wallet')

TRANSFER_PENDING_STATUSES = {'pending', 'received', 'processing', 'queued'}
TRANSFER_FAILED_STATUSES = {'failed', 'rejected', 'abandoned', 'blocked'}


class WithdrawalService(BaseService):

    def withdraw_to_bank(self, wallet, amount, bank_account, reason=None, metadata=None, reference=None,
                         fee_bearer=None, ip_address=None, user_agent=None):
        """
        Send ``amount`` from ``wallet`` to ``bank_account``.

        Returns ``(transaction, transfer_data)``. Check ``transaction.status``:
        SUCCESS (rare, synchronous), PENDING with ``transaction.requires_otp``
        (call :meth:`finalize_withdrawal`), or PENDING awaiting Paystack.
        """
        self.require_feature('WITHDRAWALS')
        if bank_account is None:
            raise BankAccountError(_("Bank account is required"))
        if bank_account.wallet_id != wallet.pk:
            raise BankAccountError(_("Bank account does not belong to this wallet"))
        if not bank_account.is_active:
            raise BankAccountError(_("Bank account is not active"))

        wallet.check_active()
        amount = wallet.validate_amount(amount)
        self.check_amount_limits(amount, 'MINIMUM_WITHDRAWAL_AMOUNT')
        reference = self.validate_reference(reference, transfer=True) or generate_transfer_reference('wdr')
        recipient_code = BankAccountService(paystack=self.paystack).ensure_recipient(bank_account)

        fee = get_fee_calculator(wallet).calculate(amount, TRANSACTION_TYPE_WITHDRAWAL, bearer=fee_bearer)
        debit_total = fee.customer_pays
        transfer_amount = fee.merchant_receives
        reason = reason or str(_("Withdrawal to {bank}").format(bank=bank_account.bank.name))

        try:
            with db_transaction.atomic():
                locked = self.lock_wallet(wallet)
                locked.check_active()
                self.check_daily_limit(locked, debit_total.amount)
                new_balance = locked.debit(debit_total, locked=True)
                txn = Transaction.objects.create(
                    wallet=locked,
                    amount=amount,
                    fees=fee.fee_amount,
                    total_amount=debit_total,
                    balance_after=new_balance,
                    ledger_sequence=locked.ledger_sequence,
                    fee_bearer=fee.bearer,
                    transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
                    direction=DIRECTION_DEBIT,
                    status=TRANSACTION_STATUS_PENDING,
                    reference=reference,
                    payment_method=PAYMENT_METHOD_BANK_TRANSFER,
                    recipient_bank_account=bank_account,
                    description=reason,
                    metadata={**(metadata or {}), 'fee': fee.to_dict(), 'transfer_amount': str(transfer_amount.amount)},
                    **self.request_context(ip_address, user_agent),
                )
                get_fee_calculator().record_fee_history(txn, fee)
        except IntegrityError as exc:
            raise DuplicateReference() from exc
        wallet.balance = new_balance

        try:
            data = self.paystack.transfers.initiate(
                amount=to_minor_units(transfer_amount.amount),
                recipient=recipient_code,
                reference=reference,
                reason=reason[:100],
                currency=wallet.currency,
            )
        except PaystackAPIError as exc:
            if exc.is_definitive:
                self._reverse(txn, reason=exc.paystack_message or exc.message, final_status=TRANSACTION_STATUS_FAILED)
                raise
            logger.warning("Withdrawal %s outcome unknown, will reconcile: %s", reference, exc)
            txn.metadata = {**txn.metadata, 'needs_reconciliation': True}
            txn.save(update_fields=['metadata', 'updated_at'])
            send_on_commit(withdrawal_initiated, sender=Transaction, transaction=txn, wallet=txn.wallet,
                           requires_otp=False)
            return txn, {'status': 'unknown', 'reference': reference}

        txn = self.apply_transfer_state(txn, data)
        send_on_commit(withdrawal_initiated, sender=Transaction, transaction=txn, wallet=txn.wallet,
                       requires_otp=txn.requires_otp)
        return txn, data

    # ------------------------------------------------------------------
    # OTP
    # ------------------------------------------------------------------

    def finalize_withdrawal(self, transaction, otp):
        """Complete a withdrawal that Paystack is holding for OTP confirmation."""
        txn = Transaction.objects.get(pk=transaction.pk)
        if txn.transaction_type != TRANSACTION_TYPE_WITHDRAWAL or not txn.is_pending:
            raise InvalidTransactionState(_("Only pending withdrawals can be finalized"))
        if not txn.paystack_transfer_code:
            raise InvalidTransactionState(_("This withdrawal has no Paystack transfer code"))
        # Invalid OTPs raise PaystackAPIError and leave the withdrawal pending so the user can retry.
        data = self.paystack.transfers.finalize(transfer_code=txn.paystack_transfer_code, otp=str(otp))
        return self.apply_transfer_state(txn, data)

    def resend_withdrawal_otp(self, transaction):
        if not transaction.paystack_transfer_code or not transaction.is_pending:
            raise InvalidTransactionState(_("This withdrawal is not waiting for an OTP"))
        return self.paystack.transfer_control.resend_otp(transaction.paystack_transfer_code, reason='transfer')

    # ------------------------------------------------------------------
    # State handling
    # ------------------------------------------------------------------

    def apply_transfer_state(self, transaction, data, webhook_event=None):
        """Apply a Paystack transfer object (initiate/finalize/verify/webhook) to a withdrawal."""
        data = data or {}
        status = (data.get('status') or '').lower()

        with db_transaction.atomic():
            txn = self.lock_transaction(transaction)
            if webhook_event is not None and webhook_event.transaction_id is None:
                webhook_event.transaction = txn
                webhook_event.save(update_fields=['transaction'])

            if data.get('transfer_code'):
                txn.paystack_transfer_code = data['transfer_code']
            if data.get('id'):
                txn.paystack_id = data['id']
            txn.paystack_reference = data.get('reference') or txn.paystack_reference
            txn.paystack_response = data

            if status == 'reversed' and txn.status in (TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING,
                                                       TRANSACTION_STATUS_SUCCESS):
                txn.save()
                return self._reverse(txn, reason=data.get('reason') or str(_("Transfer reversed")),
                                     final_status=TRANSACTION_STATUS_REVERSED)
            if txn.is_final:
                txn.save()
                return txn

            if status == 'success':
                txn.metadata = {**(txn.metadata or {}), 'requires_otp': False}
                txn.save()
                self.set_status(txn, TRANSACTION_STATUS_SUCCESS)
                self._sync_settlement(txn)
                send_on_commit(withdrawal_completed, sender=Transaction, transaction=txn, wallet=txn.wallet)
                return txn

            if status in TRANSFER_FAILED_STATUSES:
                txn.save()
                return self._reverse(txn, reason=data.get('reason') or data.get('message') or status,
                                     final_status=TRANSACTION_STATUS_FAILED)

            txn.metadata = {**(txn.metadata or {}), 'requires_otp': status == 'otp',
                            'transfer_status': status}
            txn.save()
            self._sync_settlement(txn)
            return txn

    def process_transfer_event(self, event, data, webhook_event=None):
        """Handle ``transfer.success`` / ``transfer.failed`` / ``transfer.reversed``."""
        txn = self._find_withdrawal(data)
        if txn is None:
            logger.info("Transfer event %s for unknown reference %s", event, data.get('reference'))
            return None
        status = event.split('.', 1)[1]
        return self.apply_transfer_state(txn, {**data, 'status': status}, webhook_event=webhook_event)

    def verify_withdrawal(self, transaction):
        """Fetch the transfer from Paystack and settle the local state."""
        try:
            data = self.paystack.transfers.verify(transaction.reference)
        except PaystackAPIError as exc:
            not_found = exc.status_code == 404 or (
                exc.is_definitive and 'not found' in (exc.paystack_message or '').lower()
            )
            if not_found:
                # Paystack never created the transfer: safe to give the money back.
                return self._reverse(transaction, reason=str(_("Transfer was not created by Paystack")),
                                     final_status=TRANSACTION_STATUS_FAILED)
            raise
        return self.apply_transfer_state(transaction, data)

    def reconcile_pending_withdrawals(self, older_than_minutes=None, limit=None):
        minutes = older_than_minutes if older_than_minutes is not None else wallet_settings.RECONCILE_AFTER_MINUTES
        cutoff = timezone.now() - timedelta(minutes=int(minutes))
        pending = Transaction.objects.filter(
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status__in=[TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING],
            created_at__lte=cutoff,
        ).filter(
            # Skip transfers held for OTP (nothing to verify). Written as an explicit OR because
            # exclude(key=True) silently drops rows where the key is missing (SQL NULL logic).
            Q(metadata__requires_otp__isnull=True) | Q(metadata__requires_otp=False),
        ).order_by('created_at')[:limit or int(wallet_settings.RECONCILE_BATCH_SIZE)]
        checked = 0
        for txn in pending:
            checked += 1
            try:
                self.verify_withdrawal(txn)
            except PaystackAPIError as exc:
                logger.warning("Could not verify withdrawal %s: %s", txn.reference, exc)
        return checked

    def cancel_otp_withdrawal(self, transaction, reason=None):
        """
        Give the money back for a withdrawal abandoned at the OTP step.
        Only safe because Paystack never releases an OTP transfer without the OTP.
        """
        with db_transaction.atomic():
            txn = self.lock_transaction(transaction)
            if not txn.requires_otp:
                raise InvalidTransactionState(_("Only withdrawals waiting for an OTP can be cancelled"))
            return self._reverse(txn, reason=reason or str(_("Cancelled before OTP confirmation")),
                                 final_status=TRANSACTION_STATUS_FAILED)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _reverse(self, transaction, reason, final_status):
        """Credit back a withdrawal's debit exactly once and mark it failed/reversed."""
        with db_transaction.atomic():
            txn = self.lock_transaction(transaction)
            if txn.status in (TRANSACTION_STATUS_FAILED, TRANSACTION_STATUS_REVERSED):
                return txn
            wallet = txn.wallet
            new_balance = wallet.credit(txn.total_amount, force=True)
            Transaction.objects.create(
                wallet=wallet,
                amount=txn.total_amount,
                total_amount=txn.total_amount,
                balance_after=new_balance,
                transaction_type=TRANSACTION_TYPE_REVERSAL,
                direction=DIRECTION_CREDIT,
                status=TRANSACTION_STATUS_SUCCESS,
                completed_at=timezone.now(),
                reference=f"{txn.reference}-rev",
                related_transaction=txn,
                description=str(_("Reversal of withdrawal {reference}").format(reference=txn.reference)),
                metadata={'reason': str(reason)},
            )
            txn.metadata = {**(txn.metadata or {}), 'requires_otp': False}
            txn.save(update_fields=['metadata', 'updated_at'])
            self.set_status(txn, final_status, reason=reason)
            self._sync_settlement(txn)
            send_on_commit(withdrawal_failed, sender=Transaction, transaction=txn, wallet=wallet,
                           reason=str(reason), reversed=final_status == TRANSACTION_STATUS_REVERSED)
        return txn

    @staticmethod
    def _find_withdrawal(data):
        queryset = Transaction.objects.filter(transaction_type=TRANSACTION_TYPE_WITHDRAWAL)
        reference = data.get('reference')
        if reference:
            txn = queryset.filter(reference=reference).first()
            if txn:
                return txn
        code = data.get('transfer_code')
        if code:
            return queryset.filter(paystack_transfer_code=code).first()
        return None

    @staticmethod
    def _sync_settlement(txn):
        from wallet.services.settlement_service import SettlementService
        SettlementService.sync_from_transaction(txn)
