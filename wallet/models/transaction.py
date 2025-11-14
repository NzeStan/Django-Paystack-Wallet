"""
Django Paystack Wallet - Transaction Model
Refactored with Django best practices and query optimizations
"""
from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from djmoney.models.fields import MoneyField

from wallet.models.base import BaseModel
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPES, TRANSACTION_STATUSES, PAYMENT_METHODS,
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_CANCELLED
)


class TransactionQuerySet(models.QuerySet):
    """Custom QuerySet for Transaction model with optimized queries"""
    
    def successful(self):
        """Return only successful transactions"""
        return self.filter(status=TRANSACTION_STATUS_SUCCESS)
    
    def pending(self):
        """Return only pending transactions"""
        return self.filter(status=TRANSACTION_STATUS_PENDING)
    
    def failed(self):
        """Return only failed transactions"""
        return self.filter(status=TRANSACTION_STATUS_FAILED)
    
    def cancelled(self):
        """Return only cancelled transactions"""
        return self.filter(status=TRANSACTION_STATUS_CANCELLED)
    
    def by_type(self, transaction_type):
        """
        Filter transactions by type
        
        Args:
            transaction_type: Type of transaction
            
        Returns:
            QuerySet: Filtered transactions
        """
        return self.filter(transaction_type=transaction_type)
    
    def by_wallet(self, wallet):
        """
        Filter transactions by wallet
        
        Args:
            wallet: Wallet instance
            
        Returns:
            QuerySet: Filtered transactions
        """
        return self.filter(wallet=wallet)
    
    def with_wallet_details(self):
        """Prefetch wallet and user details to avoid N+1 queries"""
        return self.select_related('wallet', 'wallet__user')
    
    def with_full_details(self):
        """Prefetch all related data for comprehensive transaction views"""
        return self.select_related(
            'wallet',
            'wallet__user',
            'recipient_wallet',
            'recipient_wallet__user',
            'recipient_bank_account',
            'recipient_bank_account__bank',
            'card',
            'related_transaction'
        )
    
    def recent(self, days=30):
        """
        Get transactions from the last N days
        
        Args:
            days: Number of days to look back
            
        Returns:
            QuerySet: Recent transactions
        """
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff_date)
    
    def in_date_range(self, start_date=None, end_date=None):
        """
        Filter transactions by date range
        
        Args:
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            QuerySet: Filtered transactions
        """
        queryset = self
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        return queryset
    
    def by_amount_range(self, min_amount=None, max_amount=None):
        """
        Filter transactions by amount range
        
        Args:
            min_amount: Minimum amount (optional)
            max_amount: Maximum amount (optional)
            
        Returns:
            QuerySet: Filtered transactions
        """
        queryset = self
        if min_amount is not None:
            queryset = queryset.filter(amount__gte=min_amount)
        if max_amount is not None:
            queryset = queryset.filter(amount__lte=max_amount)
        return queryset
    
    def with_statistics(self):
        """Annotate transactions with statistics"""
        from django.db.models import Sum, Count, Avg, Min, Max
        
        return self.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            average_amount=Avg('amount'),
            min_amount=Min('amount'),
            max_amount=Max('amount')
        )


class TransactionManager(models.Manager):
    """Custom Manager for Transaction model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return TransactionQuerySet(self.model, using=self._db)
    
    def successful(self):
        """Return only successful transactions"""
        return self.get_queryset().successful()
    
    def pending(self):
        """Return only pending transactions"""
        return self.get_queryset().pending()
    
    def failed(self):
        """Return only failed transactions"""
        return self.get_queryset().failed()
    
    def cancelled(self):
        """Return only cancelled transactions"""
        return self.get_queryset().cancelled()
    
    def by_type(self, transaction_type):
        """Get transactions by type"""
        return self.get_queryset().by_type(transaction_type)
    
    def for_wallet(self, wallet):
        """Get all transactions for a specific wallet"""
        return self.get_queryset().by_wallet(wallet)
    
    def with_wallet_details(self):
        """Get transactions with wallet details"""
        return self.get_queryset().with_wallet_details()
    
    def with_full_details(self):
        """Get transactions with full related data"""
        return self.get_queryset().with_full_details()
    
    def recent(self, days=30):
        """Get recent transactions"""
        return self.get_queryset().recent(days)
    
    def statistics(self, wallet=None, start_date=None, end_date=None):
        """
        Get transaction statistics
        
        Args:
            wallet: Filter by wallet (optional)
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            dict: Transaction statistics
        """
        queryset = self.get_queryset()
        
        if wallet:
            queryset = queryset.by_wallet(wallet)
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        return queryset.with_statistics()


class Transaction(BaseModel):
    """
    Transaction model for recording all financial activities
    
    This model represents a financial transaction within the wallet system,
    tracking deposits, withdrawals, transfers, and other monetary operations.
    """
    
    # ==========================================
    # CORE FIELDS
    # ==========================================
    
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='transactions',
        db_index=True,
        verbose_name=_('Wallet')
    )
    
    amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Amount')
    )
    
    reference = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Reference'),
        help_text=_('Unique reference for this transaction')
    )
    
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        default=TRANSACTION_TYPE_DEPOSIT,
        db_index=True,
        verbose_name=_('Transaction type')
    )
    
    status = models.CharField(
        max_length=20,
        choices=TRANSACTION_STATUSES,
        default=TRANSACTION_STATUS_PENDING,
        db_index=True,
        verbose_name=_('Status')
    )
    
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        blank=True,
        null=True,
        verbose_name=_('Payment method')
    )
    
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Description')
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_('Metadata'),
        help_text=_('Additional information about the transaction')
    )
    
    # ==========================================
    # PAYSTACK INTEGRATION FIELDS
    # ==========================================
    
    paystack_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Paystack reference')
    )
    
    paystack_response = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack response')
    )
    
    # ==========================================
    # RELATIONSHIP FIELDS
    # ==========================================
    
    recipient_wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.SET_NULL,
        related_name='received_transactions',
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Recipient wallet')
    )
    
    recipient_bank_account = models.ForeignKey(
        'wallet.BankAccount',
        on_delete=models.SET_NULL,
        related_name='transactions',
        blank=True,
        null=True,
        verbose_name=_('Recipient bank account')
    )
    
    card = models.ForeignKey(
        'wallet.Card',
        on_delete=models.SET_NULL,
        related_name='transactions',
        blank=True,
        null=True,
        verbose_name=_('Card')
    )
    
    related_transaction = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        related_name='related_transactions',
        blank=True,
        null=True,
        verbose_name=_('Related transaction'),
        help_text=_('Related transaction, e.g. refund or reversal')
    )
    
    # ==========================================
    # FINANCIAL FIELDS
    # ==========================================
    
    fees = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Fees')
    )
    
    # ==========================================
    # TRACKING FIELDS
    # ==========================================
    
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name=_('IP address')
    )
    
    user_agent = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('User agent')
    )
    
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Completed at')
    )
    
    failed_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Failed reason')
    )
    
    # Custom Manager
    objects = TransactionManager()
    
    class Meta:
        verbose_name = _('Transaction')
        verbose_name_plural = _('Transactions')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'created_at'], name='txn_wallet_created_idx'),
            models.Index(fields=['wallet', 'status'], name='txn_wallet_status_idx'),
            models.Index(fields=['transaction_type', 'status'], name='txn_type_status_idx'),
            models.Index(fields=['transaction_type', 'created_at'], name='txn_type_created_idx'),
            models.Index(fields=['status', 'created_at'], name='txn_status_created_idx'),
            models.Index(fields=['paystack_reference'], name='txn_paystack_ref_idx'),
            models.Index(fields=['reference'], name='txn_reference_idx'),
            models.Index(fields=['completed_at'], name='txn_completed_idx'),
        ]
    
    def __str__(self):
        """String representation of the transaction"""
        return f"{self.get_transaction_type_display()} - {self.amount} ({self.get_status_display()})"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return (
            f"<Transaction id={self.id} wallet_id={self.wallet_id} "
            f"type={self.transaction_type} status={self.status} "
            f"amount={self.amount} reference={self.reference}>"
        )
    
    def save(self, *args, **kwargs):
        """Override save to generate reference if not provided"""
        if not self.reference:
            from wallet.utils.id_generators import generate_transaction_reference
            self.reference = generate_transaction_reference()
        super().save(*args, **kwargs)
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def is_completed(self):
        """Check if the transaction is completed (success or failed)"""
        return self.status in [TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED]
    
    @property
    def is_successful(self):
        """Check if the transaction was successful"""
        return self.status == TRANSACTION_STATUS_SUCCESS
    
    @property
    def is_failed(self):
        """Check if the transaction failed"""
        return self.status == TRANSACTION_STATUS_FAILED
    
    @property
    def is_pending(self):
        """Check if the transaction is pending"""
        return self.status == TRANSACTION_STATUS_PENDING
    
    @property
    def is_cancelled(self):
        """Check if the transaction was cancelled"""
        return self.status == TRANSACTION_STATUS_CANCELLED
    
    @property
    def net_amount(self):
        """
        Get the net amount (amount - fees)
        
        Returns:
            Money: Net amount after fees
        """
        return self.amount - self.fees
    
    @property
    def has_fees(self):
        """Check if the transaction has fees"""
        return self.fees.amount > 0
    
    # ==========================================
    # VALIDATION METHODS
    # ==========================================
    
    def validate_amount(self):
        """
        Validate that the transaction amount is positive
        
        Returns:
            bool: True if amount is valid
            
        Raises:
            ValueError: If amount is invalid
        """
        if self.amount.amount <= 0:
            raise ValueError(_("Transaction amount must be greater than zero"))
        return True
    
    def can_be_refunded(self):
        """
        Check if the transaction can be refunded
        
        Returns:
            bool: True if transaction can be refunded
        """
        from wallet.constants import TRANSACTION_TYPE_PAYMENT
        
        return (
            self.is_successful and
            self.transaction_type in [TRANSACTION_TYPE_DEPOSIT, TRANSACTION_TYPE_PAYMENT]
        )
    
    def can_be_cancelled(self):
        """
        Check if the transaction can be cancelled
        
        Returns:
            bool: True if transaction can be cancelled
        """
        return self.is_pending
    
    def can_be_reversed(self):
        """
        Check if the transaction can be reversed
        
        Returns:
            bool: True if transaction can be reversed
        """
        return self.is_successful
    
    # ==========================================
    # BUSINESS LOGIC METHODS
    # ==========================================
    
    def mark_as_successful(self, paystack_data=None):
        """
        Mark the transaction as successful
        
        Args:
            paystack_data: Paystack response data (optional)
        """
        self.status = TRANSACTION_STATUS_SUCCESS
        self.completed_at = timezone.now()
        
        if paystack_data:
            self.paystack_response = paystack_data
            if 'reference' in paystack_data:
                self.paystack_reference = paystack_data['reference']
        
        self.save(update_fields=['status', 'completed_at', 'paystack_response', 
                                 'paystack_reference', 'updated_at'])
    
    def mark_as_failed(self, reason=None, paystack_data=None):
        """
        Mark the transaction as failed
        
        Args:
            reason: Failure reason (optional)
            paystack_data: Paystack response data (optional)
        """
        self.status = TRANSACTION_STATUS_FAILED
        self.failed_reason = reason or _("Transaction failed")
        self.completed_at = timezone.now()
        
        if paystack_data:
            self.paystack_response = paystack_data
        
        self.save(update_fields=['status', 'failed_reason', 'completed_at', 
                                 'paystack_response', 'updated_at'])
    
    def mark_as_cancelled(self, reason=None):
        """
        Mark the transaction as cancelled
        
        Args:
            reason: Cancellation reason (optional)
        """
        if not self.can_be_cancelled():
            raise ValueError(_("Only pending transactions can be cancelled"))
        
        self.status = TRANSACTION_STATUS_CANCELLED
        self.failed_reason = reason or _("Transaction cancelled")
        self.completed_at = timezone.now()
        
        self.save(update_fields=['status', 'failed_reason', 'completed_at', 'updated_at'])