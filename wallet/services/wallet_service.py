"""
``WalletService`` - one entry point for everything a wallet can do.

It combines the focused services (deposits, withdrawals, transfers, cards,
bank accounts, customers/DVA, refunds) so application code only needs::

    from wallet.services import WalletService

    service = WalletService()
    wallet = service.get_wallet(request.user)
    checkout = service.initialize_deposit(wallet, 5000)
    service.transfer(wallet, '08031234567', 1500)          # by phone number
    txn, data = service.withdraw_to_bank(wallet, 2000, bank_account)
"""
import logging
import re

from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.conf import wallet_settings
from wallet.constants import (
    DIRECTION_CREDIT,
    DIRECTION_DEBIT,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_FEE,
)
from wallet.exceptions import InvalidPhoneNumber, PaystackAPIError, RecipientError, WalletError
from wallet.models import Transaction, Wallet
from wallet.services.bank_account_service import BankAccountService
from wallet.services.card_service import CardService
from wallet.services.customer_service import CustomerService
from wallet.services.deposit_service import DepositService
from wallet.services.transaction_service import TransactionService
from wallet.services.transfer_service import TransferService
from wallet.services.withdrawal_service import WithdrawalService
from wallet.signals import send_on_commit, wallet_created, wallet_locked, wallet_unlocked
from wallet.utils.id_generators import generate_random_string, generate_wallet_tag
from wallet.utils.phone import normalize_phone_number

logger = logging.getLogger('wallet')

_TAG_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{2,29}$')


def _resolve_attr(obj, dotted):
    for part in dotted.split('.'):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


class WalletService(
    DepositService,
    WithdrawalService,
    TransferService,
    CustomerService,
    BankAccountService,
    CardService,
):
    """Facade over all wallet operations."""

    # ------------------------------------------------------------------
    # Wallet lifecycle
    # ------------------------------------------------------------------

    def get_wallet(self, user):
        """Return the user's wallet, creating (and provisioning) it if needed."""
        wallet = Wallet.objects.select_related('user').filter(user=user).first()
        if wallet is not None:
            return wallet
        return self.create_wallet(user)

    def create_wallet(self, user, tag=None, phone_number=None):
        phone_number = phone_number or self._phone_from_user(user)
        try:
            with db_transaction.atomic():
                wallet = Wallet.objects.create(
                    user=user,
                    tag=self._unique_tag(tag or generate_wallet_tag(user)),
                    phone_number=self._available_phone(phone_number),
                )
        except IntegrityError:
            # Created concurrently by another request
            return Wallet.objects.select_related('user').get(user=user)

        send_on_commit(wallet_created, sender=Wallet, wallet=wallet)
        self._provision(wallet)
        return wallet

    def _provision(self, wallet):
        """Create the Paystack customer/DVA after commit. Failures never block wallet creation."""
        if not (wallet_settings.AUTO_CREATE_PAYSTACK_CUSTOMER and wallet_settings.PAYSTACK_SECRET_KEY):
            return
        wallet_pk = wallet.pk
        create_dva = wallet_settings.AUTO_CREATE_DEDICATED_ACCOUNT and wallet_settings.ENABLE_DEDICATED_ACCOUNTS

        def _run():
            if wallet_settings.USE_CELERY:
                from wallet.tasks import setup_paystack_customer_task
                setup_paystack_customer_task.delay(str(wallet_pk), create_dva)
                return
            self.provision_wallet(Wallet.objects.get(pk=wallet_pk), create_dva)

        db_transaction.on_commit(_run)

    def provision_wallet(self, wallet, create_dedicated_account=False):
        try:
            self.ensure_customer(wallet)
            if create_dedicated_account and not wallet.dedicated_account_number:
                self.create_dedicated_account(wallet)
        except (PaystackAPIError, WalletError) as exc:
            logger.warning("Paystack provisioning for wallet %s failed: %s", wallet.pk, exc)
        return wallet

    @staticmethod
    def _unique_tag(base):
        base = re.sub(r'[^a-z0-9_.-]', '', str(base).lower())[:24] or 'wallet'
        if len(base) < 3:
            base = f"{base}{generate_random_string(4).lower()}"
        candidate = base
        for _attempt in range(20):
            if not Wallet.objects.filter(tag__iexact=candidate).exists():
                return candidate
            candidate = f"{base}{generate_random_string(4, include_uppercase=False)}"
        return f"{base}{generate_random_string(8).lower()}"

    @staticmethod
    def _phone_from_user(user):
        field = wallet_settings.USER_PHONE_FIELD
        return _resolve_attr(user, field) if field else None

    @staticmethod
    def _available_phone(phone_number):
        if not phone_number:
            return None
        try:
            normalized = normalize_phone_number(phone_number)
        except InvalidPhoneNumber:
            logger.warning("Ignoring invalid phone number on user profile: %r", phone_number)
            return None
        if Wallet.objects.filter(phone_number=normalized).exists():
            logger.warning("Phone number %s already belongs to another wallet", normalized)
            return None
        return normalized

    # ------------------------------------------------------------------
    # Identity (tag & phone used for receiving transfers)
    # ------------------------------------------------------------------

    def set_phone_number(self, wallet, phone_number):
        """Attach a phone number (normalised to E.164) so others can send money to it."""
        if not phone_number:
            wallet.phone_number = None
        else:
            normalized = normalize_phone_number(phone_number)
            if Wallet.objects.filter(phone_number=normalized).exclude(pk=wallet.pk).exists():
                raise RecipientError(_("This phone number is already linked to another wallet"))
            wallet.phone_number = normalized
        wallet.save(update_fields=['phone_number', 'updated_at'])
        return wallet

    def set_tag(self, wallet, tag):
        tag = str(tag or '').strip().lstrip('@').lower()
        if not _TAG_RE.match(tag):
            raise RecipientError(_("Tags are 3-30 characters: letters, digits, '.', '-' or '_'"))
        if Wallet.objects.filter(tag__iexact=tag).exclude(pk=wallet.pk).exists():
            raise RecipientError(_("This tag is already taken"))
        wallet.tag = tag
        wallet.save(update_fields=['tag', 'updated_at'])
        return wallet

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def lock_wallet_account(self, wallet, reason='', performed_by=None):
        wallet.lock(reason)
        self.audit('wallet.lock', performed_by, wallet=wallet.pk, reason=reason)
        send_on_commit(wallet_locked, sender=Wallet, wallet=wallet, reason=reason)
        return wallet

    def unlock_wallet_account(self, wallet, performed_by=None):
        wallet.unlock()
        self.audit('wallet.unlock', performed_by, wallet=wallet.pk)
        send_on_commit(wallet_unlocked, sender=Wallet, wallet=wallet)
        return wallet

    def get_balance(self, wallet):
        return wallet.refresh_balance()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_transaction_history(self, wallet, transaction_type=None, status=None, start_date=None, end_date=None,
                                direction=None):
        return TransactionService(paystack=self.paystack).list_transactions(
            wallet=wallet, status=status, transaction_type=transaction_type, direction=direction,
            start_date=start_date, end_date=end_date,
        )

    def get_statement(self, wallet, start_date=None, end_date=None):
        """Posted ledger entries (those that changed the balance) in chronological order."""
        return Transaction.objects.filter(wallet=wallet, ledger_sequence__isnull=False).in_date_range(
            start_date, end_date,
        ).order_by('ledger_sequence')

    # ------------------------------------------------------------------
    # Backwards-compatible helpers
    # ------------------------------------------------------------------

    def deposit(self, wallet, amount, description=None, metadata=None, transaction_reference=None):
        """
        Credit a wallet directly (no Paystack) - for bonuses, cash-back,
        manual top-ups by staff, etc.
        """
        return self.credit_wallet(wallet, amount, description=description, metadata=metadata,
                                  reference=transaction_reference)

    def withdraw(self, wallet, amount, description=None, metadata=None, transaction_reference=None):
        """Debit a wallet directly (no Paystack) - e.g. a platform charge."""
        return self.debit_wallet(wallet, amount, description=description, metadata=metadata,
                                 reference=transaction_reference)

    def credit_wallet(self, wallet, amount, description=None, metadata=None, reference=None,
                      transaction_type=None):
        amount = wallet.validate_amount(amount)
        reference = self.validate_reference(reference) or None
        with db_transaction.atomic():
            balance = wallet.credit(amount)
            txn = Transaction.objects.create(
                wallet=wallet, amount=amount, total_amount=amount, balance_after=balance,
                transaction_type=transaction_type or TRANSACTION_TYPE_DEPOSIT, direction=DIRECTION_CREDIT,
                status=TRANSACTION_STATUS_SUCCESS, completed_at=timezone.now(), reference=reference or '',
                description=description or str(_("Wallet credit")), metadata=metadata or {},
            )
        self.after_credit(wallet)
        return txn

    def debit_wallet(self, wallet, amount, description=None, metadata=None, reference=None, transaction_type=None):
        amount = wallet.validate_amount(amount)
        reference = self.validate_reference(reference) or None
        with db_transaction.atomic():
            balance = wallet.debit(amount)
            return Transaction.objects.create(
                wallet=wallet, amount=amount, total_amount=amount, balance_after=balance,
                transaction_type=transaction_type or TRANSACTION_TYPE_FEE, direction=DIRECTION_DEBIT,
                status=TRANSACTION_STATUS_SUCCESS, completed_at=timezone.now(), reference=reference or '',
                description=description or str(_("Wallet debit")), metadata=metadata or {},
            )

    def list_banks(self, country=None, currency=None):
        return BankAccountService.list_banks(self, country, currency)
