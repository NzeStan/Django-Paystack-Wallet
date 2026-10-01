"""
Wallet-to-wallet transfers and wallet payments.

Recipients can be addressed by wallet ID, tag, phone number or email
(``WALLET_TRANSFER_RECIPIENT_LOOKUP_FIELDS`` controls which are allowed)::

    service.transfer(sender_wallet, '08031234567', 5000)                     # auto-detected phone
    service.transfer(sender_wallet, 'ada', 5000, lookup='tag')
    service.transfer(sender_wallet, recipient_wallet, 5000)

Every transfer writes two ledger rows (a debit on the sender, a credit on the
recipient) inside one database transaction with both wallets locked.
"""
import logging
import uuid

from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.conf import wallet_settings
from wallet.constants import (
    DIRECTION_CREDIT,
    DIRECTION_DEBIT,
    LOOKUP_EMAIL,
    LOOKUP_ID,
    LOOKUP_PHONE,
    LOOKUP_TAG,
    PAYMENT_METHOD_WALLET,
    TRANSACTION_STATUS_CANCELLED,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_REVERSAL,
    TRANSACTION_TYPE_TRANSFER,
)
from wallet.exceptions import (
    DuplicateReference,
    CurrencyMismatchError,
    InvalidPhoneNumber,
    InvalidTransactionState,
    RecipientError,
    RecipientNotFound,
    WalletError,
)
from wallet.models import Transaction, Wallet
from wallet.services.base import BaseService
from wallet.services.fee_service import get_fee_calculator
from wallet.signals import (
    payment_cancelled,
    payment_completed,
    payment_released,
    send_on_commit,
    transfer_completed,
)
from wallet.utils.id_generators import generate_transaction_reference
from wallet.utils.phone import looks_like_phone_number, mask_phone_number, normalize_phone_number

logger = logging.getLogger('wallet')


class TransferService(BaseService):

    # ------------------------------------------------------------------
    # Recipient resolution
    # ------------------------------------------------------------------

    @staticmethod
    def allowed_lookups():
        return list(wallet_settings.TRANSFER_RECIPIENT_LOOKUP_FIELDS or [])

    def resolve_recipient(self, identifier, lookup=None):
        """
        Find the wallet identified by ``identifier``.

        ``lookup`` forces one method ('id', 'tag', 'phone_number' or 'email');
        otherwise the identifier is auto-detected: UUID -> id, contains '@' ->
        email, looks like a phone number -> phone, anything else -> tag.
        """
        if isinstance(identifier, Wallet):
            return identifier
        identifier = str(identifier or '').strip()
        if not identifier:
            raise RecipientNotFound()

        allowed = self.allowed_lookups()
        if lookup in ('phone', 'phone_number'):
            lookup = LOOKUP_PHONE
        if lookup:
            if lookup not in allowed:
                raise RecipientError(_("Finding recipients by {lookup} is not allowed").format(lookup=lookup))
            candidates = [lookup]
        else:
            candidates = self._detect_lookups(identifier)
            candidates = [c for c in candidates if c in allowed]

        for method in candidates:
            wallet = self._lookup(method, identifier)
            if wallet is not None:
                return wallet
        raise RecipientNotFound()

    @staticmethod
    def _detect_lookups(identifier):
        try:
            uuid.UUID(identifier)
            return [LOOKUP_ID]
        except ValueError:
            pass
        if identifier.startswith('@'):
            return [LOOKUP_TAG]
        if '@' in identifier:
            return [LOOKUP_EMAIL]
        if looks_like_phone_number(identifier):
            return [LOOKUP_PHONE, LOOKUP_TAG]
        return [LOOKUP_TAG]

    @staticmethod
    def _lookup(method, identifier):
        queryset = Wallet.objects.select_related('user')
        if method == LOOKUP_ID:
            try:
                return queryset.filter(pk=uuid.UUID(identifier)).first()
            except ValueError:
                return None
        if method == LOOKUP_TAG:
            return queryset.filter(tag__iexact=identifier.lstrip('@')).first()
        if method == LOOKUP_PHONE:
            try:
                phone = normalize_phone_number(identifier)
            except InvalidPhoneNumber:
                return None
            return queryset.filter(phone_number=phone).first()
        if method == LOOKUP_EMAIL:
            matches = list(queryset.filter(user__email__iexact=identifier)[:2])
            return matches[0] if len(matches) == 1 else None
        return None

    def describe_recipient(self, wallet):
        """Safe, masked details to show a sender before they confirm a transfer."""
        user = wallet.user
        full_name = ''
        if hasattr(user, 'get_full_name'):
            full_name = user.get_full_name() or ''
        parts = full_name.split()
        masked_name = ' '.join([parts[0]] + [f"{p[0]}." for p in parts[1:]]) if parts else ''
        return {
            'wallet_id': str(wallet.pk),
            'tag': wallet.tag,
            'name': masked_name or wallet.tag or '',
            'phone_number': mask_phone_number(wallet.phone_number) if wallet.phone_number else None,
            'can_receive': wallet.is_operational,
        }

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------

    def transfer(self, source_wallet, destination, amount, description=None, metadata=None, reference=None,
                 fee_bearer=None, lookup=None, ip_address=None, user_agent=None):
        """Move money between two wallets. Returns the sender's (debit) Transaction."""
        self.require_feature('INTERNAL_TRANSFERS')
        destination_wallet = self.resolve_recipient(destination, lookup)
        if destination_wallet.pk == source_wallet.pk:
            raise RecipientError(_("You cannot transfer to your own wallet"))
        if destination_wallet.currency != source_wallet.currency:
            raise CurrencyMismatchError(_("Both wallets must use the same currency"))

        amount = source_wallet.validate_amount(amount)
        self.check_amount_limits(amount)
        reference = self.validate_reference(reference) or generate_transaction_reference('TRF')
        fee = get_fee_calculator(source_wallet).calculate(amount, TRANSACTION_TYPE_TRANSFER, bearer=fee_bearer)

        sender_label = source_wallet.tag or getattr(source_wallet.user, 'email', '') or str(source_wallet.pk)
        recipient_label = destination_wallet.tag or getattr(destination_wallet.user, 'email', '') or str(
            destination_wallet.pk
        )
        context = self.request_context(ip_address, user_agent)
        now = timezone.now()

        try:
            with db_transaction.atomic():
                sender, recipient = self.lock_wallets(source_wallet, destination_wallet)
                sender.check_active()
                recipient.check_active()
                self.check_daily_limit(sender, fee.customer_pays.amount)

                sender_balance = sender.debit(fee.customer_pays, locked=True)
                recipient_balance = recipient.credit(fee.merchant_receives, locked=True)

                debit = Transaction.objects.create(
                    wallet=sender, counterparty_wallet=recipient, amount=amount, fees=fee.fee_amount,
                    total_amount=fee.customer_pays, balance_after=sender_balance, fee_bearer=fee.bearer,
                    ledger_sequence=sender.ledger_sequence,
                    transaction_type=TRANSACTION_TYPE_TRANSFER, direction=DIRECTION_DEBIT,
                    status=TRANSACTION_STATUS_SUCCESS, completed_at=now, reference=reference,
                    payment_method=PAYMENT_METHOD_WALLET,
                    description=description or str(_("Transfer to {recipient}").format(recipient=recipient_label)),
                    metadata={**(metadata or {}), 'fee': fee.to_dict()}, **context,
                )
                credit = Transaction.objects.create(
                    wallet=recipient, counterparty_wallet=sender, amount=amount, fees=fee.fee_amount,
                    total_amount=fee.merchant_receives, balance_after=recipient_balance, fee_bearer=fee.bearer,
                    ledger_sequence=recipient.ledger_sequence,
                    transaction_type=TRANSACTION_TYPE_TRANSFER, direction=DIRECTION_CREDIT,
                    status=TRANSACTION_STATUS_SUCCESS, completed_at=now, reference=f"{reference}-cr",
                    payment_method=PAYMENT_METHOD_WALLET, related_transaction=debit,
                    description=description or str(_("Transfer from {sender}").format(sender=sender_label)),
                    metadata={**(metadata or {})},
                )
                debit.related_transaction = credit
                debit.save(update_fields=['related_transaction'])
                get_fee_calculator().record_fee_history(debit, fee)
        except IntegrityError as exc:
            raise DuplicateReference() from exc

        source_wallet.balance = sender_balance
        destination_wallet.balance = recipient_balance
        send_on_commit(
            transfer_completed, sender=Transaction, transaction=debit, wallet=sender,
            recipient_transaction=credit, recipient_wallet=recipient,
        )
        self.after_credit(recipient)
        return debit

    # Backwards compatible name
    def transfer_between_wallets(self, source_wallet, destination_wallet, amount, description=None, metadata=None,
                                 reference=None, fee_bearer=None):
        return self.transfer(source_wallet, destination_wallet, amount, description=description, metadata=metadata,
                             reference=reference, fee_bearer=fee_bearer)

    # ------------------------------------------------------------------
    # Payments (checkout with wallet balance)
    # ------------------------------------------------------------------

    def pay(self, wallet, amount, merchant_wallet=None, description=None, reference=None, metadata=None,
            fee_bearer=None, escrow=False, ip_address=None, user_agent=None):
        """
        Pay for something with wallet balance.

        * ``merchant_wallet=None`` - the platform keeps the money (e.g. your own shop).
        * ``merchant_wallet=<Wallet>`` - a seller is credited (marketplace).
        * ``escrow=True`` - the buyer is debited now but the seller is only
          credited on :meth:`release_payment`; :meth:`cancel_payment` refunds
          the buyer instead.

        Returns the buyer's (debit) Transaction.
        """
        self.require_feature('PAYMENTS')
        if merchant_wallet is not None and not isinstance(merchant_wallet, Wallet):
            merchant_wallet = self.resolve_recipient(merchant_wallet)
        if merchant_wallet is not None and merchant_wallet.pk == wallet.pk:
            raise RecipientError(_("A wallet cannot pay itself"))
        if merchant_wallet is not None and merchant_wallet.currency != wallet.currency:
            raise CurrencyMismatchError(_("Both wallets must use the same currency"))
        if escrow and merchant_wallet is None:
            raise WalletError(_("Escrow payments need a merchant wallet"))

        amount = wallet.validate_amount(amount)
        self.check_amount_limits(amount)
        reference = self.validate_reference(reference) or generate_transaction_reference('PAY')
        fee = get_fee_calculator(wallet).calculate(amount, TRANSACTION_TYPE_PAYMENT, bearer=fee_bearer)
        context = self.request_context(ip_address, user_agent)
        now = timezone.now()
        merchant_txn = None

        try:
            with db_transaction.atomic():
                wallets = [wallet] + ([merchant_wallet] if merchant_wallet is not None else [])
                locked = self.lock_wallets(*wallets)
                buyer = locked[0]
                merchant = locked[1] if merchant_wallet is not None else None
                buyer.check_active()
                if merchant is not None:
                    merchant.check_active()
                self.check_daily_limit(buyer, fee.customer_pays.amount)

                buyer_balance = buyer.debit(fee.customer_pays, locked=True)
                buyer_txn = Transaction.objects.create(
                    wallet=buyer, counterparty_wallet=merchant, amount=amount, fees=fee.fee_amount,
                    total_amount=fee.customer_pays, balance_after=buyer_balance, fee_bearer=fee.bearer,
                    ledger_sequence=buyer.ledger_sequence,
                    transaction_type=TRANSACTION_TYPE_PAYMENT, direction=DIRECTION_DEBIT,
                    status=TRANSACTION_STATUS_PENDING if escrow else TRANSACTION_STATUS_SUCCESS,
                    completed_at=None if escrow else now, reference=reference, payment_method=PAYMENT_METHOD_WALLET,
                    description=description or str(_("Payment")),
                    metadata={**(metadata or {}), 'fee': fee.to_dict(), 'escrow': bool(escrow),
                              'merchant_amount': str(fee.merchant_receives.amount)},
                    **context,
                )
                get_fee_calculator().record_fee_history(buyer_txn, fee)

                if merchant is not None and not escrow:
                    merchant_txn = self._credit_merchant(buyer_txn, merchant, fee.merchant_receives, now)
        except IntegrityError as exc:
            raise DuplicateReference() from exc

        wallet.balance = buyer_balance
        send_on_commit(payment_completed, sender=Transaction, transaction=buyer_txn, wallet=buyer,
                       merchant_wallet=merchant, escrow=bool(escrow))
        if merchant_txn is not None:
            send_on_commit(payment_released, sender=Transaction, transaction=buyer_txn, wallet=buyer,
                           merchant_wallet=merchant, merchant_transaction=merchant_txn)
            self.after_credit(merchant)
        return buyer_txn

    def release_payment(self, transaction, performed_by=None):
        """Release an escrowed payment to the merchant."""
        with db_transaction.atomic():
            txn = self.lock_transaction(transaction)
            self._check_escrow(txn)
            merchant = Wallet.objects.select_for_update().get(pk=txn.counterparty_wallet_id)
            merchant_amount = Money(txn.metadata.get('merchant_amount') or txn.amount.amount, txn.amount.currency)
            merchant_txn = self._credit_merchant(txn, merchant, merchant_amount, timezone.now())
            if performed_by is not None:
                txn.metadata = {**(txn.metadata or {}), 'released_by': self.actor(performed_by)['performed_by']}
                txn.save(update_fields=['metadata', 'updated_at'])
            self.set_status(txn, TRANSACTION_STATUS_SUCCESS)
        self.audit('escrow.release', performed_by, transaction=txn.reference, amount=merchant_amount.amount)
        send_on_commit(payment_released, sender=Transaction, transaction=txn, wallet=txn.wallet,
                       merchant_wallet=merchant, merchant_transaction=merchant_txn)
        self.after_credit(merchant)
        return txn

    def cancel_payment(self, transaction, reason=None, performed_by=None):
        """Cancel an escrowed payment and refund the buyer in full."""
        with db_transaction.atomic():
            txn = self.lock_transaction(transaction)
            self._check_escrow(txn)
            buyer = txn.wallet
            new_balance = buyer.credit(txn.total_amount, force=True)
            Transaction.objects.create(
                wallet=buyer, amount=txn.total_amount, total_amount=txn.total_amount, balance_after=new_balance,
                transaction_type=TRANSACTION_TYPE_REVERSAL, direction=DIRECTION_CREDIT,
                status=TRANSACTION_STATUS_SUCCESS, completed_at=timezone.now(), reference=f"{txn.reference}-cnl",
                related_transaction=txn, payment_method=PAYMENT_METHOD_WALLET,
                description=str(_("Refund of cancelled payment {reference}").format(reference=txn.reference)),
                metadata={'reason': reason or '', **self.actor(performed_by)},
            )
            self.set_status(txn, TRANSACTION_STATUS_CANCELLED, reason=reason or str(_("Payment cancelled")))
        self.audit('escrow.cancel', performed_by, transaction=txn.reference, reason=reason or '')
        send_on_commit(payment_cancelled, sender=Transaction, transaction=txn, wallet=txn.wallet)
        return txn

    @staticmethod
    def _check_escrow(txn):
        if not (txn.transaction_type == TRANSACTION_TYPE_PAYMENT and txn.is_debit and txn.is_pending
                and (txn.metadata or {}).get('escrow') and txn.counterparty_wallet_id):
            raise InvalidTransactionState(_("Only pending escrow payments can be released or cancelled"))

    @staticmethod
    def _credit_merchant(buyer_txn, merchant, amount, when):
        new_balance = merchant.credit(amount, locked=True)
        merchant_txn = Transaction.objects.create(
            wallet=merchant, counterparty_wallet=buyer_txn.wallet, amount=buyer_txn.amount, fees=buyer_txn.fees,
            total_amount=amount, balance_after=new_balance, fee_bearer=buyer_txn.fee_bearer,
            ledger_sequence=merchant.ledger_sequence,
            transaction_type=TRANSACTION_TYPE_PAYMENT, direction=DIRECTION_CREDIT, status=TRANSACTION_STATUS_SUCCESS,
            completed_at=when, reference=f"{buyer_txn.reference}-cr", related_transaction=buyer_txn,
            payment_method=PAYMENT_METHOD_WALLET, description=buyer_txn.description,
            metadata={k: v for k, v in (buyer_txn.metadata or {}).items() if k not in ('fee',)},
        )
        buyer_txn.related_transaction = merchant_txn
        buyer_txn.save(update_fields=['related_transaction', 'updated_at'])
        return merchant_txn
