from decimal import Decimal
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from djmoney.models.fields import MoneyField
from django.utils import timezone

from wallet.exceptions import InsufficientFunds, WalletLocked, InvalidAmount, CurrencyMismatchError
from wallet.models.base import BaseModel
from wallet.settings import get_wallet_setting
from djmoney.money import Money
from wallet.models.transaction import Transaction
from wallet.constants import TRANSACTION_TYPE_DEPOSIT, TRANSACTION_STATUS_SUCCESS, TRANSACTION_TYPE_WITHDRAWAL


class Wallet(BaseModel):
    """
    Wallet model for storing user balance and wallet information
    """
    user = models.OneToOneField(
        get_wallet_setting('USER_MODEL'),
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name=_('User')
    )
    balance = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Balance')
    )
    tag = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Tag'),
        help_text=_('A custom identifier for the wallet')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    is_locked = models.BooleanField(
        default=False,
        verbose_name=_('Is locked'),
        help_text=_('Locked wallets cannot perform transactions')
    )
    last_transaction_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Last transaction date')
    )
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
        default=timezone.localdate,
        verbose_name=_('Daily transaction reset')
    )
    paystack_customer_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Paystack customer code')
    )
    dedicated_account_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_('Dedicated account number')
    )
    dedicated_account_bank = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Dedicated account bank')
    )
    
    class Meta:
        verbose_name = _('Wallet')
        verbose_name_plural = _('Wallets')
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.user}'s wallet ({self.balance})"
    
    def lock(self):
        """Lock the wallet to prevent transactions"""
        self.is_locked = True
        self.save(update_fields=['is_locked', 'updated_at'])
    
    def unlock(self):
        """Unlock the wallet to allow transactions"""
        self.is_locked = False
        self.save(update_fields=['is_locked', 'updated_at'])
    
    def check_active(self):
        """Check if the wallet is active and not locked"""
        if not self.is_active:
            raise WalletLocked(_("Wallet is inactive"))
        if self.is_locked:
            raise WalletLocked()
    
    def reset_daily_limit(self):
        """Reset daily transaction limits if a new day has started"""
        
        today = timezone.now().date()
        if self.daily_transaction_reset != today:
            self.daily_transaction_total = Money(0, self.daily_transaction_total.currency)
            self.daily_transaction_count = 0
            self.daily_transaction_reset = today
            self.save(update_fields=[
                'daily_transaction_total', 
                'daily_transaction_count', 
                'daily_transaction_reset',
                'updated_at'
            ])
    
    def update_transaction_metrics(self, amount):
        """Update transaction metrics when a new transaction occurs"""

        self.last_transaction_date = timezone.now()

        # Reset daily limits if it's a new day
        self.reset_daily_limit()

        # Validate amount is Money object
        if isinstance(amount, (Decimal, int, float)):
            amount = Money(amount, self.balance.currency)  # Auto-convert if wallet has currency
        elif not isinstance(amount, Money):
            raise InvalidAmount(f"Expected Money object, got {type(amount)}")

        # Currency consistency check
        if amount.currency != self.daily_transaction_total.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet uses {self.daily_transaction_total.currency}, "
                f"but got {amount.currency}"
            )

        # Prevent negative daily total
        new_total = self.daily_transaction_total + amount
        if new_total.amount < 0:
            raise InvalidAmount(new_total)

        # Update fields
        self.daily_transaction_total = new_total
        self.daily_transaction_count += 1

        self.save(update_fields=[
            'last_transaction_date',
            'daily_transaction_total',
            'daily_transaction_count',
            'updated_at'
        ])
    
    @transaction.atomic
    def deposit(self, amount):
        """
        Add funds to the wallet
        
        Args:
            amount (Decimal): Amount to add to wallet
            
        Returns:
           Money: The updated balance of the wallet
            
        Raises:
            WalletLocked: If the wallet is locked
            InvalidAmount: If the amount is invalid
            CurrencyMismatchError: If currencies don't match
        """
        
        self.check_active()
        
        # Validate amount is Money object
        if isinstance(amount, (Decimal, int, float)):
            amount = Money(amount, self.balance.currency)  # Auto-convert if wallet has currency
        elif not isinstance(amount, Money):
            raise InvalidAmount(f"Expected Money object, got {type(amount)}")
        
        # Validate positive amount
        if amount.amount <= 0:
            raise InvalidAmount(amount)
        
        # Validate currency match
        if amount.currency != self.balance.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet uses {self.balance.currency}, "
                f"but got {amount.currency}"
            )
        
        # Add to balance
        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])
        
        # # Create transaction record
        # transaction = Transaction.objects.create(
        #     wallet=self,
        #     amount=amount,
        #     transaction_type=TRANSACTION_TYPE_DEPOSIT,
        #     status=TRANSACTION_STATUS_SUCCESS,
        #     description=_("Deposit to wallet")
        # )
        
        # Update transaction metrics
        self.update_transaction_metrics(amount.amount)
        
        return self.balance
    
    @transaction.atomic
    def withdraw(self, amount):
        """
        Remove funds from the wallet
        
        Args:
            amount (Decimal): Amount to remove from wallet
            
        Returns:
            Money: The updated balance of the wallet            
            
        Raises:
            WalletLocked: If the wallet is locked
            InvalidAmount: If the amount is invalid
            InsufficientFunds: If the wallet has insufficient funds
            CurrencyMismatchError: If currencies don't match
        """
        
        self.check_active()
        
        # Validate amount is Money object
        if isinstance(amount, (Decimal, int, float)):
            amount = Money(amount, self.balance.currency)  # Auto-convert if wallet has currency
        elif not isinstance(amount, Money):
            raise InvalidAmount(f"Expected Money object, got {type(amount)}")
        
        # Validate positive amount
        if amount.amount <= 0:
            raise InvalidAmount(amount)
        
        # Validate currency match
        if amount.currency != self.balance.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet uses {self.balance.currency}, "
                f"but got {amount.currency}"
            )
        
        # Check if enough funds
        if self.balance < amount:
            raise InsufficientFunds(self, amount)
        
        # Subtract from balance
        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])
        
        # # Create transaction record
        # transaction = Transaction.objects.create(
        #     wallet=self,
        #     amount=amount,
        #     transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
        #     status=TRANSACTION_STATUS_SUCCESS,
        #     description=_("Withdrawal from wallet")
        # )
        
        # Update transaction metrics
        self.update_transaction_metrics(amount.amount)
        
        return self.balance
    
    
    @transaction.atomic
    def transfer(self, destination_wallet, amount, description= None):
        """
        Transfer funds to another wallet
        
        Args:
            destination_wallet (Wallet): The wallet to transfer funds to
            amount (Decimal): Amount to transfer
            description (str, optional): Description for the transaction
            
        Returns:
            tuple (Money): (source_balance, destination_balance)
            
        Raises:
            WalletLocked: If either wallet is locked
            InvalidAmount: If the amount is invalid
            InsufficientFunds: If the source wallet has insufficient funds
            CurrencyMismatchError: If currencies don't match
        """
        from wallet.models.transaction import Transaction
        from wallet.constants import TRANSACTION_TYPE_TRANSFER, TRANSACTION_STATUS_SUCCESS

        self.check_active()
        destination_wallet.check_active()

        # Validate amount is Money object
        if isinstance(amount, (Decimal, int, float)):
            amount = Money(amount, self.balance.currency)  # Auto-convert if wallet has currency
        elif not isinstance(amount, Money):
            raise InvalidAmount(f"Expected Money object, got {type(amount)}")

        # Validate positive amount
        if amount.amount <= 0:
            raise InvalidAmount(amount)

        # Validate currency match for source wallet
        if amount.currency != self.balance.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: source wallet uses {self.balance.currency}, "
                f"but got {amount.currency}"
            )

        # Validate currency match for destination wallet
        if amount.currency != destination_wallet.balance.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: destination wallet uses {destination_wallet.balance.currency}, "
                f"but got {amount.currency}"
            )

        # Check if enough funds
        if self.balance < amount:
            raise InsufficientFunds(self, amount)

        # Default description
        if description is None:
            description = _("Transfer to {recipient}").format(recipient=destination_wallet.user)
        
        # Subtract from source wallet
        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])
        
        # Add to destination wallet
        destination_wallet.balance += amount
        destination_wallet.save(update_fields=['balance', 'updated_at'])
        
        # Create transaction records
        transaction = Transaction.objects.create(
            wallet=self,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_SUCCESS,
            description=description,
            recipient_wallet=destination_wallet
        )
        
        # Create the corresponding transaction for the recipient
        Transaction.objects.create(
            wallet=destination_wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_SUCCESS,
            description=_("Transfer from {sender}").format(sender=self.user),
            related_transaction=transaction
        )
        
        # Update transaction metrics for both wallets
        self.update_transaction_metrics(amount)
        destination_wallet.update_transaction_metrics(amount)
        
        return (self.balance, destination_wallet.balance)