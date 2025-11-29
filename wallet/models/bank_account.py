from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from wallet.models.base import BaseModel
from wallet.constants import BANK_ACCOUNT_TYPES, BANK_ACCOUNT_TYPE_SAVINGS


# ==========================================
# BANK QUERYSET AND MANAGER
# ==========================================

class BankQuerySet(models.QuerySet):
    """Custom QuerySet for Bank model with optimized queries"""
    
    def active(self):
        """Return only active banks"""
        return self.filter(is_active=True)
    
    def inactive(self):
        """Return only inactive banks"""
        return self.filter(is_active=False)
    
    def by_country(self, country):
        """
        Filter banks by country
        
        Args:
            country (str): Country code
            
        Returns:
            QuerySet: Filtered banks
        """
        return self.filter(country=country)
    
    def by_currency(self, currency):
        """
        Filter banks by currency
        
        Args:
            currency (str): Currency code
            
        Returns:
            QuerySet: Filtered banks
        """
        return self.filter(currency=currency)
    
    def search(self, query):
        """
        Search banks by name or code
        
        Args:
            query (str): Search query
            
        Returns:
            QuerySet: Filtered banks
        """
        from django.db.models import Q
        return self.filter(
            Q(name__icontains=query) | 
            Q(code__icontains=query) |
            Q(slug__icontains=query)
        )


class BankManager(models.Manager):
    """Custom Manager for Bank model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return BankQuerySet(self.model, using=self._db)
    
    def active(self):
        """Return only active banks"""
        return self.get_queryset().active()
    
    def inactive(self):
        """Return only inactive banks"""
        return self.get_queryset().inactive()
    
    def by_country(self, country):
        """Get banks by country"""
        return self.get_queryset().by_country(country)
    
    def by_currency(self, currency):
        """Get banks by currency"""
        return self.get_queryset().by_currency(currency)
    
    def search(self, query):
        """Search banks"""
        return self.get_queryset().search(query)
    
    def get_by_code(self, code):
        """
        Get bank by code
        
        Args:
            code (str): Bank code
            
        Returns:
            Bank: Bank instance
            
        Raises:
            Bank.DoesNotExist: If bank not found
        """
        return self.get(code=code)


# ==========================================
# BANK ACCOUNT QUERYSET AND MANAGER
# ==========================================

class BankAccountQuerySet(models.QuerySet):
    """Custom QuerySet for BankAccount model with optimized queries"""
    
    def active(self):
        """Return only active bank accounts"""
        return self.filter(is_active=True)
    
    def inactive(self):
        """Return only inactive bank accounts"""
        return self.filter(is_active=False)
    
    def verified(self):
        """Return only verified bank accounts"""
        return self.filter(is_verified=True)
    
    def unverified(self):
        """Return only unverified bank accounts"""
        return self.filter(is_verified=False)
    
    def defaults(self):
        """Return only default bank accounts"""
        return self.filter(is_default=True)
    
    def by_wallet(self, wallet):
        """
        Filter bank accounts by wallet
        
        Args:
            wallet: Wallet instance
            
        Returns:
            QuerySet: Filtered bank accounts
        """
        return self.filter(wallet=wallet)
    
    def by_bank(self, bank):
        """
        Filter bank accounts by bank
        
        Args:
            bank: Bank instance
            
        Returns:
            QuerySet: Filtered bank accounts
        """
        return self.filter(bank=bank)
    
    def by_account_type(self, account_type):
        """
        Filter bank accounts by account type
        
        Args:
            account_type (str): Account type
            
        Returns:
            QuerySet: Filtered bank accounts
        """
        return self.filter(account_type=account_type)
    
    def with_wallet_details(self):
        """Prefetch wallet and user details to avoid N+1 queries"""
        return self.select_related('wallet', 'wallet__user')
    
    def with_bank_details(self):
        """Prefetch bank details to avoid N+1 queries"""
        return self.select_related('bank')
    
    def with_full_details(self):
        """Prefetch all related data for comprehensive views"""
        return self.select_related(
            'wallet',
            'wallet__user',
            'bank'
        ).prefetch_related(
            'transactions',
            'settlements'
        )
    
    def with_transaction_count(self):
        """Annotate bank accounts with transaction count"""
        from django.db.models import Count
        return self.annotate(transaction_count=Count('transactions'))
    
    def with_settlement_count(self):
        """Annotate bank accounts with settlement count"""
        from django.db.models import Count
        return self.annotate(settlement_count=Count('settlements'))
    
    def with_statistics(self):
        """Annotate bank accounts with comprehensive statistics"""
        from django.db.models import Count, Sum, Q
        from wallet.constants import TRANSACTION_STATUS_SUCCESS, SETTLEMENT_STATUS_SUCCESS
        
        return self.annotate(
            total_transactions=Count('transactions'),
            successful_transactions=Count(
                'transactions',
                filter=Q(transactions__status=TRANSACTION_STATUS_SUCCESS)
            ),
            total_settlements=Count('settlements'),
            successful_settlements=Count(
                'settlements',
                filter=Q(settlements__status=SETTLEMENT_STATUS_SUCCESS)
            ),
            total_settled_amount=Sum(
                'settlements__amount',
                filter=Q(settlements__status=SETTLEMENT_STATUS_SUCCESS)
            )
        )
    
    def search(self, query):
        """
        Search bank accounts by account number or name
        
        Args:
            query (str): Search query
            
        Returns:
            QuerySet: Filtered bank accounts
        """
        from django.db.models import Q
        return self.filter(
            Q(account_number__icontains=query) |
            Q(account_name__icontains=query) |
            Q(bank__name__icontains=query)
        )


class BankAccountManager(models.Manager):
    """Custom Manager for BankAccount model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return BankAccountQuerySet(self.model, using=self._db)
    
    def active(self):
        """Return only active bank accounts"""
        return self.get_queryset().active()
    
    def inactive(self):
        """Return only inactive bank accounts"""
        return self.get_queryset().inactive()
    
    def verified(self):
        """Return only verified bank accounts"""
        return self.get_queryset().verified()
    
    def unverified(self):
        """Return only unverified bank accounts"""
        return self.get_queryset().unverified()
    
    def defaults(self):
        """Return only default bank accounts"""
        return self.get_queryset().defaults()
    
    def for_wallet(self, wallet):
        """Get all bank accounts for a specific wallet"""
        return self.get_queryset().by_wallet(wallet)
    
    def by_bank(self, bank):
        """Get bank accounts by bank"""
        return self.get_queryset().by_bank(bank)
    
    def by_account_type(self, account_type):
        """Get bank accounts by account type"""
        return self.get_queryset().by_account_type(account_type)
    
    def with_wallet_details(self):
        """Get bank accounts with wallet details"""
        return self.get_queryset().with_wallet_details()
    
    def with_bank_details(self):
        """Get bank accounts with bank details"""
        return self.get_queryset().with_bank_details()
    
    def with_full_details(self):
        """Get bank accounts with full related data"""
        return self.get_queryset().with_full_details()
    
    def search(self, query):
        """Search bank accounts"""
        return self.get_queryset().search(query)
    
    @transaction.atomic
    def get_or_create_for_wallet(self, wallet, bank_code, account_number, **extra_fields):
        """
        Get or create a bank account for a wallet (atomic operation)
        
        Args:
            wallet: Wallet instance
            bank_code (str): Bank code
            account_number (str): Account number
            **extra_fields: Additional fields
            
        Returns:
            tuple: (BankAccount instance, created boolean)
        """
        from wallet.models import Bank
        bank = Bank.objects.get_by_code(bank_code)
        return self.get_or_create(
            wallet=wallet,
            bank=bank,
            account_number=account_number,
            defaults=extra_fields
        )


# ==========================================
# MODELS
# ==========================================

class Bank(BaseModel):
    """
    Bank model for storing bank information from Paystack
    
    This model stores information about banks that can be used for
    withdrawal and settlement operations.
    """
    
    # Basic Information
    name = models.CharField(
        max_length=255,
        verbose_name=_('Name'),
        help_text=_('Bank name')
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name=_('Code'),
        help_text=_('Unique bank code')
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name=_('Slug'),
        help_text=_('URL-friendly bank identifier')
    )
    
    # Location and Currency
    country = models.CharField(
        max_length=2,
        default='NG',
        verbose_name=_('Country'),
        help_text=_('Country code (ISO 3166-1 alpha-2)')
    )
    currency = models.CharField(
        max_length=3,
        default='NGN',
        verbose_name=_('Currency'),
        help_text=_('Currency code (ISO 4217)')
    )
    
    # Additional Information
    type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_('Type'),
        help_text=_('Bank type (e.g., commercial, microfinance)')
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_('Is active'),
        help_text=_('Whether the bank is currently active for transactions')
    )
    
    # Paystack Integration
    paystack_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack data'),
        help_text=_('Additional data from Paystack API')
    )
    
    # Custom Manager
    objects = BankManager()
    
    class Meta:
        verbose_name = _('Bank')
        verbose_name_plural = _('Banks')
        ordering = ['name']
        indexes = [
            models.Index(fields=['code'], name='bank_code_idx'),
            models.Index(fields=['country'], name='bank_country_idx'),
            models.Index(fields=['is_active'], name='bank_active_idx'),
        ]
    
    def __str__(self):
        """String representation of the bank"""
        return f"{self.name} ({self.code})"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return f"<Bank id={self.id} code={self.code} name={self.name}>"


class BankAccount(BaseModel):
    """
    Bank account model for storing user bank account information
    
    This model stores bank account details for withdrawal and settlement
    operations. It integrates with Paystack for account verification and
    transfer recipient creation.
    """
    
    # Relationships
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        db_index=True,
        verbose_name=_('Wallet'),
        help_text=_('Wallet that owns this bank account')
    )
    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,
        related_name='bank_accounts',
        db_index=True,
        verbose_name=_('Bank'),
        help_text=_('Bank where the account is held')
    )
    
    # Account Details
    account_number = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name=_('Account number'),
        help_text=_('Bank account number')
    )
    account_name = models.CharField(
        max_length=255,
        verbose_name=_('Account name'),
        help_text=_('Name on the bank account')
    )
    account_type = models.CharField(
        max_length=20,
        choices=BANK_ACCOUNT_TYPES,
        default=BANK_ACCOUNT_TYPE_SAVINGS,
        verbose_name=_('Account type'),
        help_text=_('Type of bank account')
    )
    
    # Verification
    bvn = models.CharField(
        max_length=11,
        blank=True,
        null=True,
        verbose_name=_('BVN'),
        help_text=_('Bank Verification Number')
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_('Is verified'),
        help_text=_('Whether the account has been verified with Paystack')
    )
    
    # Status
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_('Is default'),
        help_text=_('Whether this is the default account for the wallet')
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_('Is active'),
        help_text=_('Whether the account is currently active')
    )
    
    # Paystack Integration
    paystack_recipient_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        unique=True,
        verbose_name=_('Paystack recipient code'),
        help_text=_('Paystack transfer recipient code')
    )
    paystack_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack data'),
        help_text=_('Additional data from Paystack API')
    )
    
    # Custom Manager
    objects = BankAccountManager()
    
    class Meta:
        verbose_name = _('Bank account')
        verbose_name_plural = _('Bank accounts')
        ordering = ['-is_default', '-created_at']
        unique_together = ('wallet', 'bank', 'account_number')
        indexes = [
            models.Index(fields=['wallet', 'is_default'], name='bankacct_wallet_default_idx'),
            models.Index(fields=['wallet', 'is_active'], name='bankacct_wallet_active_idx'),
            models.Index(fields=['paystack_recipient_code'], name='bankacct_recipient_idx'),
            models.Index(fields=['is_verified'], name='bankacct_verified_idx'),
        ]
    
    def __str__(self):
        """String representation of the bank account"""
        return f"{self.account_name} - {self.bank.name} ({self.account_number})"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return (
            f"<BankAccount id={self.id} wallet_id={self.wallet_id} "
            f"bank={self.bank.code} account={self.account_number}>"
        )
    
    def save(self, *args, **kwargs):
        """
        Override save to handle default account logic
        
        If this account is being set as default, unset any other default
        accounts for this wallet.
        """
        if self.is_default:
            # Unset other default accounts for this wallet
            BankAccount.objects.filter(
                wallet=self.wallet,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        
        super().save(*args, **kwargs)
    
    # ==========================================
    # PUBLIC METHODS
    # ==========================================
    
    @transaction.atomic
    def set_as_default(self):
        """
        Set this account as the default account for the wallet
        
        This method ensures that only one account is set as default
        per wallet by unsetting other default accounts atomically.
        
        Returns:
            None
        """
        # Unset other default accounts
        BankAccount.objects.filter(
            wallet=self.wallet,
            is_default=True
        ).exclude(pk=self.pk).update(is_default=False)
        
        # Set this as default
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])
    
    @transaction.atomic
    def remove(self):
        """
        Mark the account as inactive instead of deleting it
        
        This is a soft delete that preserves historical data while
        preventing the account from being used in new transactions.
        If this was the default account, another active account will
        be set as default.
        
        Returns:
            None
        """
        was_default = self.is_default
        
        # Mark as inactive and remove default status
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
        
        # If this was default, set another active account as default
        if was_default:
            new_default = BankAccount.objects.filter(
                wallet=self.wallet,
                is_active=True
            ).first()
            
            if new_default:
                new_default.set_as_default()
    
    @transaction.atomic
    def verify(self):
        """
        Mark the account as verified
        
        This should be called after successful verification with Paystack.
        
        Returns:
            None
        """
        self.is_verified = True
        self.save(update_fields=['is_verified', 'updated_at'])
    
    @transaction.atomic
    def activate(self):
        """
        Activate the account
        
        Returns:
            None
        """
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])
    
    @transaction.atomic
    def deactivate(self):
        """
        Deactivate the account
        
        Returns:
            None
        """
        self.is_active = False
        if self.is_default:
            self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def masked_account_number(self):
        """
        Get masked account number (e.g., '****7890')
        
        Returns:
            str: Masked account number
        """
        if len(self.account_number) > 4:
            return f"{'*' * (len(self.account_number) - 4)}{self.account_number[-4:]}"
        return self.account_number
    
    @property
    def full_bank_name(self):
        """
        Get full bank name with account type
        
        Returns:
            str: Full bank name
        """
        return f"{self.bank.name} ({self.get_account_type_display()})"
    
    @property
    def display_name(self):
        """
        Get display name for the account
        
        Returns:
            str: Display name
        """
        return f"{self.account_name} - {self.bank.name} ({self.masked_account_number})"