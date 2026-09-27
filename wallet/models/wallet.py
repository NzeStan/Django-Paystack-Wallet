from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.conf import wallet_settings
from wallet.exceptions import (
    CurrencyMismatchError,
    InsufficientFunds,
    InvalidAmount,
    InvalidPin,
    MinimumBalanceViolation,
    PinLocked,
    PinNotSet,
    WalletInactive,
    WalletLocked,
)
from wallet.models.base import BaseModel
from wallet.models.fields import WalletMoneyField


class WalletQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, is_locked=False)

    def locked(self):
        return self.filter(is_locked=True)

    def with_user_details(self):
        return self.select_related('user')

    def with_full_details(self):
        return self.select_related('user').prefetch_related('cards', 'bank_accounts')

    def with_transaction_summary(self):
        from django.db.models import Count
        from wallet.constants import TRANSACTION_STATUS_SUCCESS

        return self.annotate(
            total_transactions=Count('transactions'),
            successful_transactions=Count(
                'transactions', filter=Q(transactions__status=TRANSACTION_STATUS_SUCCESS)
            ),
        )


class WalletManager(models.Manager.from_queryset(WalletQuerySet)):
    def get_or_create_for_user(self, user):
        return self.get_or_create(user=user)


class Wallet(BaseModel):
    """
    A user's wallet.

    The balance must only ever be changed through :meth:`credit` / :meth:`debit`
    (or the services built on them). Both lock the wallet row with
    ``SELECT ... FOR UPDATE`` so concurrent requests cannot overspend.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name=_('User'),
    )
    balance = WalletMoneyField(default=0, verbose_name=_('Balance'))

    tag = models.CharField(
        max_length=50, unique=True, blank=True, null=True,
        verbose_name=_('Tag'),
        help_text=_('Public handle other users can send money to'),
    )
    phone_number = models.CharField(
        max_length=20, unique=True, blank=True, null=True,
        verbose_name=_('Phone number'),
        help_text=_('E.164 phone number other users can send money to'),
    )

    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_('Is active'))
    is_locked = models.BooleanField(default=False, db_index=True, verbose_name=_('Is locked'))
    locked_reason = models.CharField(max_length=255, blank=True, default='', verbose_name=_('Locked reason'))
    last_transaction_date = models.DateTimeField(null=True, blank=True, verbose_name=_('Last transaction date'))
    ledger_sequence = models.PositiveBigIntegerField(
        default=0, editable=False, verbose_name=_('Ledger sequence'),
        help_text=_('Incremented on every balance change; orders the statement deterministically'),
    )

    daily_limit = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True,
        verbose_name=_('Daily limit'),
        help_text=_('Overrides WALLET_MAXIMUM_DAILY_TRANSACTION for this wallet'),
    )

    # Transaction PIN (optional, see WALLET_REQUIRE_TRANSACTION_PIN)
    pin_hash = models.CharField(max_length=128, blank=True, default='', editable=False)
    failed_pin_attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    pin_locked_until = models.DateTimeField(null=True, blank=True, editable=False)

    # Paystack customer
    paystack_customer_code = models.CharField(
        max_length=100, unique=True, blank=True, null=True, verbose_name=_('Paystack customer code'),
    )
    paystack_customer_id = models.BigIntegerField(null=True, blank=True, verbose_name=_('Paystack customer ID'))
    customer_identified = models.BooleanField(
        default=False, verbose_name=_('Customer identified'),
        help_text=_('Paystack customer identity validation succeeded'),
    )

    # Dedicated virtual account
    dedicated_account_id = models.BigIntegerField(null=True, blank=True, verbose_name=_('Dedicated account ID'))
    dedicated_account_number = models.CharField(
        max_length=20, blank=True, null=True, db_index=True, verbose_name=_('Dedicated account number'),
    )
    dedicated_account_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_('Dedicated account name'),
    )
    dedicated_account_bank = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_('Dedicated account bank'),
    )
    dedicated_account_bank_slug = models.CharField(max_length=100, blank=True, null=True)
    dedicated_account_active = models.BooleanField(default=False)

    metadata = models.JSONField(default=dict, blank=True, verbose_name=_('Metadata'))

    objects = WalletManager()

    class Meta:
        verbose_name = _('Wallet')
        verbose_name_plural = _('Wallets')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'is_locked'], name='wallet_status_idx'),
        ]

    def __str__(self):
        user_display = getattr(self.user, 'email', None) or str(self.user)
        return f"Wallet ({user_display}) - {self.balance}"

    def __repr__(self):
        return f"<Wallet id={self.id} user_id={self.user_id} balance={self.balance}>"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def currency(self):
        return str(self.balance.currency)

    @property
    def available_balance(self):
        return self.balance

    @property
    def is_operational(self):
        return self.is_active and not self.is_locked

    @property
    def has_pin(self):
        return bool(self.pin_hash)

    @property
    def pin_is_locked(self):
        return bool(self.pin_locked_until and self.pin_locked_until > timezone.now())

    @property
    def has_dedicated_account(self):
        return bool(self.dedicated_account_number)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def check_active(self):
        """Raise if the wallet cannot send or receive money."""
        if not self.is_active:
            raise WalletInactive(message=_("Wallet is inactive"))
        if self.is_locked:
            raise WalletLocked(self)

    def validate_amount(self, amount):
        """Normalise ``amount`` to a positive Money in the wallet's currency."""
        from wallet.utils.money import to_decimal

        if isinstance(amount, Money):
            if str(amount.currency) != self.currency:
                raise CurrencyMismatchError(
                    _("Currency mismatch: wallet uses {wallet}, got {got}").format(
                        wallet=self.currency, got=amount.currency
                    )
                )
            value = to_decimal(amount.amount)
        elif isinstance(amount, (Decimal, int, float, str)):
            value = to_decimal(amount)
        else:
            raise InvalidAmount(message=f"Unsupported amount type {type(amount).__name__}")

        if value <= 0:
            raise InvalidAmount(value)
        return Money(value, self.currency)

    def validate_sufficient_funds(self, amount):
        amount = amount if isinstance(amount, Money) else Money(amount, self.currency)
        if self.balance < amount:
            raise InsufficientFunds(self, amount)

    # ------------------------------------------------------------------
    # Balance primitives (row-locked)
    # ------------------------------------------------------------------

    def _locked_copy(self):
        return type(self).objects.select_for_update().get(pk=self.pk)

    def _sync_from(self, locked):
        self.balance = locked.balance
        self.last_transaction_date = locked.last_transaction_date
        self.ledger_sequence = locked.ledger_sequence
        self.updated_at = locked.updated_at

    def _target(self, locked):
        """The row to change: ``self`` if the caller already holds its lock, else a fresh locked copy."""
        if locked:
            if not transaction.get_connection().in_atomic_block:
                raise RuntimeError("locked=True requires an open transaction holding the wallet's row lock")
            return self
        return self._locked_copy()

    def credit(self, amount, force=False, locked=False):
        """
        Add ``amount`` to the balance and return the new balance.

        ``force=True`` credits even a locked/inactive wallet. Use it only for
        money that has already arrived (deposits, refunds, reversals).
        ``locked=True`` means this instance came from ``select_for_update()`` in the
        current transaction (skips re-locking).
        """
        if locked:
            return self._credit(amount, force, locked=True)
        with transaction.atomic():
            return self._credit(amount, force)

    def _credit(self, amount, force=False, locked=False):
        amount = self.validate_amount(amount)
        locked = self._target(locked)
        if not force:
            locked.check_active()
        locked.balance = locked.balance + amount
        locked.last_transaction_date = timezone.now()
        locked.ledger_sequence += 1
        locked.save(update_fields=['balance', 'balance_currency', 'last_transaction_date', 'ledger_sequence',
                                   'updated_at'])
        self._sync_from(locked)
        return locked.balance

    def debit(self, amount, enforce_minimum_balance=True, force=False, locked=False):
        """
        Remove ``amount`` from the balance and return the new balance.

        Raises InsufficientFunds / MinimumBalanceViolation / WalletLocked.
        ``locked=True``: see :meth:`credit`.
        """
        if locked:
            return self._debit(amount, enforce_minimum_balance, force, locked=True)
        with transaction.atomic():
            return self._debit(amount, enforce_minimum_balance, force)

    def _debit(self, amount, enforce_minimum_balance=True, force=False, locked=False):
        amount = self.validate_amount(amount)
        locked = self._target(locked)
        if not force:
            locked.check_active()
        if locked.balance < amount:
            raise InsufficientFunds(locked, amount)
        if enforce_minimum_balance:
            minimum = Decimal(str(wallet_settings.MINIMUM_BALANCE or 0))
            if locked.balance.amount - amount.amount < minimum:
                raise MinimumBalanceViolation(
                    _("This transaction would leave less than the minimum balance of {minimum}").format(
                        minimum=Money(minimum, locked.currency)
                    )
                )
        locked.balance = locked.balance - amount
        locked.last_transaction_date = timezone.now()
        locked.ledger_sequence += 1
        locked.save(update_fields=['balance', 'balance_currency', 'last_transaction_date', 'ledger_sequence',
                                   'updated_at'])
        self._sync_from(locked)
        return locked.balance

    # Backwards compatible names
    def deposit(self, amount):
        return self.credit(amount)

    def withdraw(self, amount):
        return self.debit(amount)

    def refresh_balance(self):
        self.refresh_from_db(fields=['balance', 'balance_currency'])
        return self.balance

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------

    def lock(self, reason=''):
        self.is_locked = True
        self.locked_reason = reason or ''
        self.save(update_fields=['is_locked', 'locked_reason', 'updated_at'])
        return True

    def unlock(self):
        self.is_locked = False
        self.locked_reason = ''
        self.save(update_fields=['is_locked', 'locked_reason', 'updated_at'])
        return True

    def activate(self):
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])
        return True

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])
        return True

    # ------------------------------------------------------------------
    # Transaction PIN
    # ------------------------------------------------------------------

    def set_pin(self, raw_pin):
        self.pin_hash = make_password(str(raw_pin))
        self.failed_pin_attempts = 0
        self.pin_locked_until = None
        self.save(update_fields=['pin_hash', 'failed_pin_attempts', 'pin_locked_until', 'updated_at'])

    def clear_pin(self):
        self.pin_hash = ''
        self.failed_pin_attempts = 0
        self.pin_locked_until = None
        self.save(update_fields=['pin_hash', 'failed_pin_attempts', 'pin_locked_until', 'updated_at'])

    def verify_pin(self, raw_pin):
        """Check the PIN, counting failures and locking out after too many. Raises on failure."""
        if not self.has_pin:
            raise PinNotSet()
        if self.pin_is_locked:
            raise PinLocked()

        if raw_pin is not None and check_password(str(raw_pin), self.pin_hash):
            if self.failed_pin_attempts:
                self.failed_pin_attempts = 0
                self.pin_locked_until = None
                self.save(update_fields=['failed_pin_attempts', 'pin_locked_until', 'updated_at'])
            return True

        self.failed_pin_attempts += 1
        fields = ['failed_pin_attempts', 'updated_at']
        if self.failed_pin_attempts >= int(wallet_settings.PIN_MAX_ATTEMPTS):
            self.pin_locked_until = timezone.now() + timedelta(minutes=int(wallet_settings.PIN_LOCKOUT_MINUTES))
            self.failed_pin_attempts = 0
            fields.append('pin_locked_until')
            self.save(update_fields=fields)
            raise PinLocked()
        self.save(update_fields=fields)
        raise InvalidPin()

    # ------------------------------------------------------------------
    # Limits & stats
    # ------------------------------------------------------------------

    def get_daily_limit(self):
        if self.daily_limit is not None:
            return self.daily_limit
        limit = wallet_settings.MAXIMUM_DAILY_TRANSACTION
        return Decimal(str(limit)) if limit is not None else None

    def get_daily_outgoing_total(self):
        """Total money that left this wallet today (pending or successful debits)."""
        from wallet.constants import (
            DIRECTION_DEBIT,
            TRANSACTION_STATUS_PENDING,
            TRANSACTION_STATUS_PROCESSING,
            TRANSACTION_STATUS_SUCCESS,
            TRANSACTION_TYPE_PAYMENT,
            TRANSACTION_TYPE_TRANSFER,
            TRANSACTION_TYPE_WITHDRAWAL,
        )

        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        total = self.transactions.filter(
            direction=DIRECTION_DEBIT,
            transaction_type__in=[TRANSACTION_TYPE_WITHDRAWAL, TRANSACTION_TYPE_TRANSFER, TRANSACTION_TYPE_PAYMENT],
            status__in=[TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING, TRANSACTION_STATUS_SUCCESS],
            created_at__gte=start,
        ).aggregate(total=Sum('total_amount'))['total']
        return total or Decimal('0')

    def get_transaction_count(self):
        return self.transactions.count()

    def has_pending_transactions(self):
        from wallet.constants import TRANSACTION_STATUS_PENDING
        return self.transactions.filter(status=TRANSACTION_STATUS_PENDING).exists()
