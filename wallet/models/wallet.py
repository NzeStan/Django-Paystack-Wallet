from decimal import Decimal
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from djmoney.models.fields import MoneyField
from djmoney.money import Money

from wallet.exceptions import (
    InsufficientFunds,
    WalletLocked,
    InvalidAmount,
    CurrencyMismatchError
)
from wallet.models.base import BaseModel
from wallet.settings import get_wallet_setting


class WalletQuerySet(models.QuerySet):
    """Custom QuerySet for Wallet model with optimized queries"""
    
    def active(self):
        """Return only active wallets"""
        return self.filter(is_active=True, is_locked=False)
    
    def locked(self):
        """Return only locked wallets"""
        return self.filter(is_locked=True)
    
    def with_user_details(self):
        """Prefetch user details to avoid N+1 queries"""
        return self.select_related('user')
    
    def with_full_details(self):
        """Prefetch all related data for comprehensive wallet views"""
        return self.select_related('user').prefetch_related(
            'transactions',
            'cards',
            'bank_accounts',
            'received_transactions'
        )
    
    def with_transaction_summary(self):
        """Annotate wallets with transaction statistics"""
        from django.db.models import Count, Sum, Q
        from wallet.constants import TRANSACTION_STATUS_SUCCESS
        
        return self.annotate(
            total_transactions=Count('transactions'),
            successful_transactions=Count(
                'transactions',
                filter=Q(transactions__status=TRANSACTION_STATUS_SUCCESS)
            ),
            total_received=Sum(
                'received_transactions__amount',
                filter=Q(received_transactions__status=TRANSACTION_STATUS_SUCCESS)
            )
        )


class WalletManager(models.Manager):
    """Custom Manager for Wallet model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return WalletQuerySet(self.model, using=self._db)
    
    def active(self):
        """Return only active wallets"""
        return self.get_queryset().active()
    
    def with_user_details(self):
        """Get wallets with user details"""
        return self.get_queryset().with_user_details()
    
    def with_full_details(self):
        """Get wallets with full related data"""
        return self.get_queryset().with_full_details()
    
    def get_or_create_for_user(self, user):
        """
        Get or create a wallet for a user (atomic operation)
        
        Args:
            user: User instance
            
        Returns:
            tuple: (Wallet instance, created boolean)
        """
        return self.get_or_create(user=user)


class Wallet(BaseModel):
    """
    Wallet model for storing user balance and wallet information
    
    This model represents a digital wallet that can hold monetary balance,
    track transactions, and enforce business rules for financial operations.
    """
    
    # Core Fields
    user = models.OneToOneField(
        get_wallet_setting('USER_MODEL'),
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name=_('User'),
        help_text=_('The user who owns this wallet')
    )
    
    balance = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Balance'),
        help_text=_('Current balance in the wallet')
    )
    
    # Optional Identifiers
    tag = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Tag'),
        help_text=_('A custom identifier for the wallet')
    )
    
    # Status Fields
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_('Is active'),
        help_text=_('Whether the wallet is active and can perform operations')
    )
    
    is_locked = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_('Is locked'),
        help_text=_('Locked wallets cannot perform transactions')
    )
    
    # Transaction Tracking
    last_transaction_date = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_('Last transaction date'),
        help_text=_('Date and time of the last transaction')
    )
    
    # Daily Limits Tracking
    daily_transaction_total = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Daily transaction total'),
        help_text=_('Total amount transacted today')
    )
    
    daily_transaction_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Daily transaction count'),
        help_text=_('Number of transactions performed today')
    )
    
    daily_transaction_reset = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Daily transaction reset date'),
        help_text=_('Date when daily limits were last reset')
    )
    
    # Paystack Integration Fields
    paystack_customer_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        unique=True,
        verbose_name=_('Paystack customer code'),
        help_text=_('Paystack customer identifier')
    )
    
    dedicated_account_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Dedicated account number'),
        help_text=_('Virtual account number for direct deposits')
    )
    
    dedicated_account_bank = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Dedicated account bank'),
        help_text=_('Bank name for the dedicated account')
    )
    
    # Custom Manager
    objects = WalletManager()
    
    class Meta:
        verbose_name = _('Wallet')
        verbose_name_plural = _('Wallets')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user'], name='wallet_user_idx'),
            models.Index(fields=['is_active', 'is_locked'], name='wallet_status_idx'),
            models.Index(fields=['tag'], name='wallet_tag_idx'),
            models.Index(fields=['paystack_customer_code'], name='wallet_paystack_idx'),
            models.Index(fields=['last_transaction_date'], name='wallet_last_txn_idx'),
        ]
    
    def __str__(self):
        """String representation of the wallet"""
        user_display = getattr(self.user, 'email', str(self.user))
        return f"Wallet ({user_display}) - {self.balance}"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return (
            f"<Wallet id={self.id} user_id={self.user_id} "
            f"balance={self.balance} active={self.is_active}>"
        )
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def available_balance(self):
        """
        Get the available balance (alias for balance)
        
        Returns:
            Money: Available balance
        """
        return self.balance
    
    @property
    def is_operational(self):
        """
        Check if wallet can perform operations
        
        Returns:
            bool: True if active and not locked
        """
        return self.is_active and not self.is_locked
    
    @property
    def needs_daily_reset(self):
        """
        Check if daily limits need to be reset
        
        Returns:
            bool: True if reset is needed
        """
        if not self.daily_transaction_reset:
            return True
        return self.daily_transaction_reset < timezone.now().date()
    
    # ==========================================
    # VALIDATION METHODS
    # ==========================================
    
    def check_active(self):
        """
        Verify wallet is active and unlocked
        
        Raises:
            WalletLocked: If wallet is locked or inactive
        """
        if not self.is_active:
            raise WalletLocked(_("Wallet is inactive"))
        
        if self.is_locked:
            raise WalletLocked(self)
    
    def validate_amount(self, amount):
        """
        Validate and normalize amount to Money object
        
        Args:
            amount: Amount to validate (Decimal, int, float, or Money)
            
        Returns:
            Money: Validated Money object
            
        Raises:
            InvalidAmount: If amount is invalid
            CurrencyMismatchError: If currencies don't match
        """
        # Convert to Money if needed
        if isinstance(amount, (Decimal, int, float)):
            amount = Money(amount, self.balance.currency)
        elif not isinstance(amount, Money):
            raise InvalidAmount(f"Expected Money object, got {type(amount).__name__}")
        
        # Validate positive amount
        if amount.amount <= 0:
            raise InvalidAmount(amount)
        
        # Validate currency match
        if amount.currency != self.balance.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet uses {self.balance.currency}, "
                f"but got {amount.currency}"
            )
        
        return amount
    
    def validate_sufficient_funds(self, amount):
        """
        Verify wallet has sufficient funds for withdrawal
        
        Args:
            amount (Money): Amount to check
            
        Raises:
            InsufficientFunds: If balance is insufficient
        """
        if self.balance < amount:
            raise InsufficientFunds(self, amount)
    
    # ==========================================
    # STATUS MANAGEMENT
    # ==========================================
    
    def lock(self):
        """
        Lock the wallet to prevent transactions
        
        Returns:
            bool: True if locked successfully
        """
        if not self.is_locked:
            self.is_locked = True
            self.save(update_fields=['is_locked', 'updated_at'])
        return True
    
    def unlock(self):
        """
        Unlock the wallet to allow transactions
        
        Returns:
            bool: True if unlocked successfully
        """
        if self.is_locked:
            self.is_locked = False
            self.save(update_fields=['is_locked', 'updated_at'])
        return True
    
    def deactivate(self):
        """
        Deactivate the wallet
        
        Returns:
            bool: True if deactivated successfully
        """
        if self.is_active:
            self.is_active = False
            self.save(update_fields=['is_active', 'updated_at'])
        return True
    
    def activate(self):
        """
        Activate the wallet
        
        Returns:
            bool: True if activated successfully
        """
        if not self.is_active:
            self.is_active = True
            self.save(update_fields=['is_active', 'updated_at'])
        return True
    
    # ==========================================
    # DAILY LIMITS MANAGEMENT
    # ==========================================
    
    def reset_daily_limit(self):
        """
        Reset daily transaction limits if needed
        
        This method is automatically called during transactions
        to ensure daily limits are properly managed.
        """
        if self.needs_daily_reset:
            self.daily_transaction_total = Money(0, self.balance.currency)
            self.daily_transaction_count = 0
            self.daily_transaction_reset = timezone.now().date()
            self.save(update_fields=[
                'daily_transaction_total',
                'daily_transaction_count',
                'daily_transaction_reset',
                'updated_at'
            ])
    
    def update_transaction_metrics(self, amount):
        """
        Update daily transaction metrics
        
        Args:
            amount (Decimal): Transaction amount to add to daily total
            
        Raises:
            InvalidAmount: If amount is invalid
            CurrencyMismatchError: If currencies don't match
        """
        # Update last transaction date
        self.last_transaction_date = timezone.now()
        
        # Reset daily limits if needed
        self.reset_daily_limit()
        
        # Validate and convert amount
        if isinstance(amount, (Decimal, int, float)):
            amount = Money(amount, self.balance.currency)
        elif not isinstance(amount, Money):
            raise InvalidAmount(f"Expected Money object, got {type(amount).__name__}")
        
        # Validate currency match
        if amount.currency != self.daily_transaction_total.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet uses {self.daily_transaction_total.currency}, "
                f"but got {amount.currency}"
            )
        
        # Prevent negative daily total
        new_total = self.daily_transaction_total + amount
        if new_total.amount < 0:
            raise InvalidAmount(f"Negative daily total not allowed: {new_total}")
        
        # Update metrics
        self.daily_transaction_total = new_total
        self.daily_transaction_count += 1
        
        # Save updates
        self.save(update_fields=[
            'last_transaction_date',
            'daily_transaction_total',
            'daily_transaction_count',
            'updated_at'
        ])
    
    # ==========================================
    # CORE WALLET OPERATIONS
    # ==========================================
    
    @transaction.atomic
    def deposit(self, amount):
        """
        Add funds to the wallet
        
        This method handles the core deposit operation, updating the wallet
        balance and transaction metrics. Transaction records should be
        created by the service layer.
        
        Args:
            amount: Amount to deposit (Money, Decimal, int, or float)
            
        Returns:
            Money: Updated balance
            
        Raises:
            WalletLocked: If wallet is locked or inactive
            InvalidAmount: If amount is invalid
            CurrencyMismatchError: If currencies don't match
        """
        # Verify wallet is operational
        self.check_active()
        
        # Validate and normalize amount
        amount = self.validate_amount(amount)
        
        # Add to balance
        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])
        
        # Update transaction metrics
        self.update_transaction_metrics(amount.amount)
        
        return self.balance
    
    @transaction.atomic
    def withdraw(self, amount):
        """
        Remove funds from the wallet
        
        This method handles the core withdrawal operation, updating the wallet
        balance and transaction metrics. Transaction records should be
        created by the service layer.
        
        Args:
            amount: Amount to withdraw (Money, Decimal, int, or float)
            
        Returns:
            Money: Updated balance
            
        Raises:
            WalletLocked: If wallet is locked or inactive
            InvalidAmount: If amount is invalid
            InsufficientFunds: If balance is insufficient
            CurrencyMismatchError: If currencies don't match
        """
        # Verify wallet is operational
        self.check_active()
        
        # Validate and normalize amount
        amount = self.validate_amount(amount)
        
        # Verify sufficient funds
        self.validate_sufficient_funds(amount)
        
        # Subtract from balance
        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])
        
        # Update transaction metrics
        self.update_transaction_metrics(amount.amount)
        
        return self.balance
    
    @transaction.atomic
    def transfer(self, destination_wallet, amount, description=None):
        """
        Transfer funds to another wallet
        
        This method handles wallet-to-wallet transfers by withdrawing from
        this wallet and depositing to the destination wallet. Transaction
        records should be created by the service layer.
        
        Args:
            destination_wallet (Wallet): Destination wallet
            amount: Amount to transfer (Money, Decimal, int, or float)
            description (str, optional): Transfer description
            
        Returns:
            tuple: (source_balance, destination_balance)
            
        Raises:
            WalletLocked: If either wallet is locked or inactive
            InvalidAmount: If amount is invalid
            InsufficientFunds: If source wallet has insufficient funds
            CurrencyMismatchError: If currencies don't match
        """
        # Verify both wallets are operational
        self.check_active()
        destination_wallet.check_active()
        
        # Validate and normalize amount
        amount = self.validate_amount(amount)
        
        # Validate currency match between wallets
        if amount.currency != destination_wallet.balance.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: source wallet uses {amount.currency}, "
                f"destination wallet uses {destination_wallet.balance.currency}"
            )
        
        # Verify sufficient funds
        self.validate_sufficient_funds(amount)
        
        # Perform transfer (withdrawal from source, deposit to destination)
        source_balance = self.withdraw(amount)
        destination_balance = destination_wallet.deposit(amount)
        
        return source_balance, destination_balance
    
    # ==========================================
    # UTILITY METHODS
    # ==========================================
    
    def refresh_balance(self):
        """
        Refresh balance from database
        
        Useful when balance might have been updated by another process
        """
        self.refresh_from_db(fields=['balance', 'balance_currency'])
    
    def get_transaction_count(self):
        """
        Get total transaction count
        
        Returns:
            int: Total number of transactions
        """
        return self.transactions.count()
    
    def get_successful_transactions_count(self):
        """
        Get count of successful transactions
        
        Returns:
            int: Number of successful transactions
        """
        from wallet.constants import TRANSACTION_STATUS_SUCCESS
        return self.transactions.filter(status=TRANSACTION_STATUS_SUCCESS).count()
    
    def get_pending_transactions_count(self):
        """
        Get count of pending transactions
        
        Returns:
            int: Number of pending transactions
        """
        from wallet.constants import TRANSACTION_STATUS_PENDING
        return self.transactions.filter(status=TRANSACTION_STATUS_PENDING).count()
    
    def has_pending_transactions(self):
        """
        Check if wallet has any pending transactions
        
        Returns:
            bool: True if there are pending transactions
        """
        from wallet.constants import TRANSACTION_STATUS_PENDING
        return self.transactions.filter(status=TRANSACTION_STATUS_PENDING).exists()