from decimal import Decimal
from django.db import models
from django.db import transaction as db_transaction
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from djmoney.models.fields import MoneyField
from djmoney.money import Money

from wallet.models.base import BaseModel
from wallet.constants import (
    SETTLEMENT_STATUSES,
    SETTLEMENT_STATUS_PENDING,
    SETTLEMENT_STATUS_PROCESSING,
    SETTLEMENT_STATUS_SUCCESS,
    SETTLEMENT_STATUS_FAILED,
    SETTLEMENT_SCHEDULE_TYPES,
    SETTLEMENT_SCHEDULE_MANUAL,
    SETTLEMENT_SCHEDULE_DAILY,
    SETTLEMENT_SCHEDULE_WEEKLY,
    SETTLEMENT_SCHEDULE_MONTHLY,
    SETTLEMENT_SCHEDULE_THRESHOLD
)
from wallet.settings import get_wallet_setting


class SettlementQuerySet(models.QuerySet):
    """Custom QuerySet for Settlement model with optimized queries"""
    
    def pending(self):
        """Return only pending settlements"""
        return self.filter(status=SETTLEMENT_STATUS_PENDING)
    
    def processing(self):
        """Return only processing settlements"""
        return self.filter(status=SETTLEMENT_STATUS_PROCESSING)
    
    def successful(self):
        """Return only successful settlements"""
        return self.filter(status=SETTLEMENT_STATUS_SUCCESS)
    
    def failed(self):
        """Return only failed settlements"""
        return self.filter(status=SETTLEMENT_STATUS_FAILED)
    
    def completed(self):
        """Return completed settlements (successful or failed)"""
        return self.filter(
            status__in=[SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED]
        )
    
    def by_wallet(self, wallet):
        """
        Filter settlements by wallet
        
        Args:
            wallet: Wallet instance
            
        Returns:
            QuerySet: Filtered settlements
        """
        return self.filter(wallet=wallet)
    
    def by_bank_account(self, bank_account):
        """
        Filter settlements by bank account
        
        Args:
            bank_account: BankAccount instance
            
        Returns:
            QuerySet: Filtered settlements
        """
        return self.filter(bank_account=bank_account)
    
    def with_wallet_details(self):
        """Prefetch wallet and user details to avoid N+1 queries"""
        return self.select_related('wallet', 'wallet__user')
    
    def with_bank_details(self):
        """Prefetch bank account and bank details to avoid N+1 queries"""
        return self.select_related('bank_account', 'bank_account__bank')
    
    def with_full_details(self):
        """Prefetch all related data for comprehensive settlement views"""
        return self.select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank',
            'transaction'
        )
    
    def recent(self, days=30):
        """
        Get settlements from the last N days
        
        Args:
            days: Number of days to look back
            
        Returns:
            QuerySet: Recent settlements
        """
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff_date)
    
    def in_date_range(self, start_date=None, end_date=None):
        """
        Filter settlements by date range
        
        Args:
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            QuerySet: Filtered settlements
        """
        queryset = self
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        return queryset
    
    def by_amount_range(self, min_amount=None, max_amount=None):
        """
        Filter settlements by amount range
        
        Args:
            min_amount: Minimum amount (optional)
            max_amount: Maximum amount (optional)
            
        Returns:
            QuerySet: Filtered settlements
        """
        queryset = self
        if min_amount is not None:
            queryset = queryset.filter(amount__gte=min_amount)
        if max_amount is not None:
            queryset = queryset.filter(amount__lte=max_amount)
        return queryset
    
    def with_statistics(self):
        """Annotate settlements with statistics"""
        from django.db.models import Sum, Count, Avg, Min, Max
        
        return self.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            average_amount=Avg('amount'),
            min_amount=Min('amount'),
            max_amount=Max('amount'),
            total_fees=Sum('fees')
        )
    
    def by_reference(self, reference):
        """
        Get settlement by reference
        
        Args:
            reference: Settlement reference
            
        Returns:
            Settlement: Settlement instance
        """
        return self.get(reference=reference)
    
    def by_paystack_transfer_code(self, transfer_code):
        """
        Get settlement by Paystack transfer code
        
        Args:
            transfer_code: Paystack transfer code
            
        Returns:
            Settlement: Settlement instance
        """
        return self.get(paystack_transfer_code=transfer_code)


class SettlementManager(models.Manager):
    """Custom Manager for Settlement model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return SettlementQuerySet(self.model, using=self._db)
    
    def pending(self):
        """Return only pending settlements"""
        return self.get_queryset().pending()
    
    def processing(self):
        """Return only processing settlements"""
        return self.get_queryset().processing()
    
    def successful(self):
        """Return only successful settlements"""
        return self.get_queryset().successful()
    
    def failed(self):
        """Return only failed settlements"""
        return self.get_queryset().failed()
    
    def completed(self):
        """Return completed settlements"""
        return self.get_queryset().completed()
    
    def for_wallet(self, wallet):
        """Get all settlements for a specific wallet"""
        return self.get_queryset().by_wallet(wallet)
    
    def with_wallet_details(self):
        """Get settlements with wallet details"""
        return self.get_queryset().with_wallet_details()
    
    def with_bank_details(self):
        """Get settlements with bank details"""
        return self.get_queryset().with_bank_details()
    
    def with_full_details(self):
        """Get settlements with full related data"""
        return self.get_queryset().with_full_details()
    
    def recent(self, days=30):
        """Get recent settlements"""
        return self.get_queryset().recent(days)
    
    def statistics(self, wallet=None, start_date=None, end_date=None):
        """
        Get settlement statistics
        
        Args:
            wallet: Filter by wallet (optional)
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            dict: Settlement statistics
        """
        queryset = self.get_queryset()
        
        if wallet:
            queryset = queryset.by_wallet(wallet)
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        return queryset.with_statistics()


class Settlement(BaseModel):
    """
    Settlement model for tracking wallet settlements to bank accounts
    
    This model represents a settlement/withdrawal transaction where wallet funds
    are transferred to a user's bank account via Paystack.
    """
    
    # ==========================================
    # CORE FIELDS
    # ==========================================
    
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='settlements',
        db_index=True,
        verbose_name=_('Wallet')
    )
    
    bank_account = models.ForeignKey(
        'wallet.BankAccount',
        on_delete=models.SET_NULL,
        related_name='settlements',
        null=True,
        db_index=True,
        verbose_name=_('Bank account')
    )
    
    amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Amount'),
        help_text=_('Amount to settle to bank account')
    )
    
    fees = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Fees'),
        help_text=_('Transaction fees charged for settlement')
    )
    
    status = models.CharField(
        max_length=20,
        choices=SETTLEMENT_STATUSES,
        default=SETTLEMENT_STATUS_PENDING,
        db_index=True,
        verbose_name=_('Status')
    )
    
    reference = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        db_index=True,
        verbose_name=_('Reference'),
        help_text=_('Unique reference for this settlement')
    )
    
    # ==========================================
    # PAYSTACK INTEGRATION FIELDS
    # ==========================================
    
    paystack_transfer_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Paystack transfer code'),
        help_text=_('Transfer code from Paystack')
    )
    
    paystack_transfer_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack transfer data'),
        help_text=_('Complete transfer data from Paystack')
    )
    
    # ==========================================
    # ADDITIONAL FIELDS
    # ==========================================
    
    reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Reason'),
        help_text=_('Reason for settlement')
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_('Metadata'),
        help_text=_('Additional settlement metadata')
    )
    
    transaction = models.OneToOneField(
        'wallet.Transaction',
        on_delete=models.SET_NULL,
        related_name='settlement',
        null=True,
        blank=True,
        verbose_name=_('Transaction'),
        help_text=_('Associated wallet transaction')
    )
    
    settled_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('Settled at'),
        help_text=_('Date and time when settlement was completed')
    )
    
    failure_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Failure reason'),
        help_text=_('Reason for settlement failure')
    )
    
    # ==========================================
    # MANAGER
    # ==========================================
    
    objects = SettlementManager()
    
    # ==========================================
    # META
    # ==========================================
    
    class Meta:
        verbose_name = _('Settlement')
        verbose_name_plural = _('Settlements')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'status']),
            models.Index(fields=['reference']),
            models.Index(fields=['paystack_transfer_code']),
            models.Index(fields=['created_at']),
            models.Index(fields=['settled_at']),
        ]
    
    # ==========================================
    # STRING REPRESENTATION
    # ==========================================
    
    def __str__(self):
        """String representation of settlement"""
        return f"Settlement {self.reference} - {self.amount} ({self.get_status_display()})"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return (
            f"<Settlement id={self.id} reference={self.reference} "
            f"amount={self.amount} status={self.status}>"
        )
    
    # ==========================================
    # SAVE OVERRIDE
    # ==========================================
    
    def save(self, *args, **kwargs):
        """
        Override save to generate reference if not provided
        
        Args:
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments
        """
        # Generate a reference if not provided
        if not self.reference:
            from wallet.utils.id_generators import generate_settlement_reference
            self.reference = generate_settlement_reference()
        
        super().save(*args, **kwargs)
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def is_pending(self):
        """Check if settlement is pending"""
        return self.status == SETTLEMENT_STATUS_PENDING
    
    @property
    def is_processing(self):
        """Check if settlement is processing"""
        return self.status == SETTLEMENT_STATUS_PROCESSING
    
    @property
    def is_successful(self):
        """Check if settlement is successful"""
        return self.status == SETTLEMENT_STATUS_SUCCESS
    
    @property
    def is_failed(self):
        """Check if settlement is failed"""
        return self.status == SETTLEMENT_STATUS_FAILED
    
    @property
    def is_completed(self):
        """Check if settlement is completed (successful or failed)"""
        return self.status in [SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED]
    
    @property
    def net_amount(self):
        """Calculate net amount (amount - fees)"""
        return self.amount - self.fees
    
    @property
    def processing_time(self):
        """Calculate processing time if settlement is completed"""
        if self.settled_at:
            return self.settled_at - self.created_at
        return None
    
    # ==========================================
    # METHODS
    # ==========================================
    
    @db_transaction.atomic
    def mark_as_processing(self):
        """
        Mark settlement as processing
        
        Returns:
            Settlement: Updated settlement instance
        """
        self.status = SETTLEMENT_STATUS_PROCESSING
        self.save(update_fields=['status'])
        return self
    
    @db_transaction.atomic
    def mark_as_success(self, paystack_data=None):
        """
        Mark settlement as successful
        
        Args:
            paystack_data: Paystack transfer data (optional)
            
        Returns:
            Settlement: Updated settlement instance
        """
        self.status = SETTLEMENT_STATUS_SUCCESS
        self.settled_at = timezone.now()
        
        if paystack_data:
            self.paystack_transfer_data = paystack_data
        
        self.save(update_fields=['status', 'settled_at', 'paystack_transfer_data'])
        return self
    
    @db_transaction.atomic
    def mark_as_failed(self, reason=None, paystack_data=None):
        """
        Mark settlement as failed
        
        Args:
            reason: Failure reason (optional)
            paystack_data: Paystack transfer data (optional)
            
        Returns:
            Settlement: Updated settlement instance
        """
        self.status = SETTLEMENT_STATUS_FAILED
        
        if reason:
            self.failure_reason = reason
        
        if paystack_data:
            self.paystack_transfer_data = paystack_data
        
        self.save(update_fields=['status', 'failure_reason', 'paystack_transfer_data'])
        return self


# ==========================================
# SETTLEMENT SCHEDULE QUERYSET AND MANAGER
# ==========================================


class SettlementScheduleQuerySet(models.QuerySet):
    """Custom QuerySet for SettlementSchedule model with optimized queries"""
    
    def active(self):
        """Return only active schedules"""
        return self.filter(is_active=True)
    
    def inactive(self):
        """Return only inactive schedules"""
        return self.filter(is_active=False)
    
    def by_wallet(self, wallet):
        """
        Filter schedules by wallet
        
        Args:
            wallet: Wallet instance
            
        Returns:
            QuerySet: Filtered schedules
        """
        return self.filter(wallet=wallet)
    
    def by_schedule_type(self, schedule_type):
        """
        Filter schedules by type
        
        Args:
            schedule_type: Schedule type
            
        Returns:
            QuerySet: Filtered schedules
        """
        return self.filter(schedule_type=schedule_type)
    
    def due_now(self):
        """
        Get schedules that are due for processing now
        
        Returns:
            QuerySet: Due schedules
        """
        now = timezone.now()
        return self.filter(
            is_active=True,
            next_settlement__lte=now
        ).exclude(
            schedule_type=SETTLEMENT_SCHEDULE_MANUAL
        )
    
    def threshold_based(self):
        """
        Get threshold-based schedules
        
        Returns:
            QuerySet: Threshold schedules
        """
        return self.filter(
            is_active=True,
            schedule_type=SETTLEMENT_SCHEDULE_THRESHOLD
        ).exclude(
            amount_threshold=None
        )
    
    def with_wallet_details(self):
        """Prefetch wallet and user details to avoid N+1 queries"""
        return self.select_related('wallet', 'wallet__user')
    
    def with_bank_details(self):
        """Prefetch bank account and bank details to avoid N+1 queries"""
        return self.select_related('bank_account', 'bank_account__bank')
    
    def with_full_details(self):
        """Prefetch all related data for comprehensive schedule views"""
        return self.select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank'
        )


class SettlementScheduleManager(models.Manager):
    """Custom Manager for SettlementSchedule model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return SettlementScheduleQuerySet(self.model, using=self._db)
    
    def active(self):
        """Return only active schedules"""
        return self.get_queryset().active()
    
    def inactive(self):
        """Return only inactive schedules"""
        return self.get_queryset().inactive()
    
    def for_wallet(self, wallet):
        """Get all schedules for a specific wallet"""
        return self.get_queryset().by_wallet(wallet)
    
    def due_now(self):
        """Get schedules that are due for processing"""
        return self.get_queryset().due_now()
    
    def threshold_based(self):
        """Get threshold-based schedules"""
        return self.get_queryset().threshold_based()
    
    def with_wallet_details(self):
        """Get schedules with wallet details"""
        return self.get_queryset().with_wallet_details()
    
    def with_bank_details(self):
        """Get schedules with bank details"""
        return self.get_queryset().with_bank_details()
    
    def with_full_details(self):
        """Get schedules with full related data"""
        return self.get_queryset().with_full_details()


class SettlementSchedule(BaseModel):
    """
    Settlement schedule model for automatically settling wallet funds
    
    This model defines rules for automatic settlements, including schedule type,
    frequency, and amount thresholds.
    """
    
    # ==========================================
    # CORE FIELDS
    # ==========================================
    
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='settlement_schedules',
        db_index=True,
        verbose_name=_('Wallet')
    )
    
    bank_account = models.ForeignKey(
        'wallet.BankAccount',
        on_delete=models.CASCADE,
        related_name='settlement_schedules',
        db_index=True,
        verbose_name=_('Bank account')
    )
    
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_('Is active'),
        help_text=_('Whether this schedule is active')
    )
    
    schedule_type = models.CharField(
        max_length=20,
        choices=SETTLEMENT_SCHEDULE_TYPES,
        default=SETTLEMENT_SCHEDULE_MANUAL,
        db_index=True,
        verbose_name=_('Schedule type')
    )
    
    # ==========================================
    # AMOUNT FIELDS
    # ==========================================
    
    amount_threshold = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        blank=True,
        null=True,
        verbose_name=_('Amount threshold'),
        help_text=_('Threshold amount for threshold-based settlements')
    )
    
    minimum_amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Minimum amount'),
        help_text=_('Minimum amount to settle')
    )
    
    maximum_amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        blank=True,
        null=True,
        verbose_name=_('Maximum amount'),
        help_text=_('Maximum amount to settle (optional)')
    )
    
    # ==========================================
    # SCHEDULE TIMING FIELDS
    # ==========================================
    
    day_of_week = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_('Day of week'),
        help_text=_('Day of week for weekly settlements (0=Monday, 6=Sunday)')
    )
    
    day_of_month = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_('Day of month'),
        help_text=_('Day of month for monthly settlements (1-31)')
    )
    
    time_of_day = models.TimeField(
        blank=True,
        null=True,
        verbose_name=_('Time of day'),
        help_text=_('Time of day for scheduled settlements')
    )
    
    # ==========================================
    # TRACKING FIELDS
    # ==========================================
    
    last_settlement = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('Last settlement'),
        help_text=_('Date and time of last settlement')
    )
    
    next_settlement = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Next settlement'),
        help_text=_('Date and time of next scheduled settlement')
    )
    
    # ==========================================
    # MANAGER
    # ==========================================
    
    objects = SettlementScheduleManager()
    
    # ==========================================
    # META
    # ==========================================
    
    class Meta:
        verbose_name = _('Settlement Schedule')
        verbose_name_plural = _('Settlement Schedules')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'is_active']),
            models.Index(fields=['schedule_type']),
            models.Index(fields=['next_settlement']),
        ]
    
    # ==========================================
    # STRING REPRESENTATION
    # ==========================================
    
    def __str__(self):
        """String representation of settlement schedule"""
        return f"{self.wallet} - {self.get_schedule_type_display()} ({self.is_active})"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return (
            f"<SettlementSchedule id={self.id} wallet={self.wallet_id} "
            f"type={self.schedule_type} active={self.is_active}>"
        )
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def is_due(self):
        """Check if schedule is due for processing"""
        if not self.is_active or not self.next_settlement:
            return False
        return timezone.now() >= self.next_settlement
    
    @property
    def is_threshold_based(self):
        """Check if this is a threshold-based schedule"""
        return self.schedule_type == SETTLEMENT_SCHEDULE_THRESHOLD
    
    @property
    def is_time_based(self):
        """Check if this is a time-based schedule"""
        return self.schedule_type in [
            SETTLEMENT_SCHEDULE_DAILY,
            SETTLEMENT_SCHEDULE_WEEKLY,
            SETTLEMENT_SCHEDULE_MONTHLY
        ]
    
    # ==========================================
    # METHODS
    # ==========================================
    
    def calculate_next_settlement(self):
        """
        Calculate the next settlement date based on schedule type
        
        Returns:
            SettlementSchedule: Updated schedule instance
        """
        from datetime import timedelta
        
        now = timezone.now()
        
        # Manual schedules don't have automatic next settlement
        if self.schedule_type == SETTLEMENT_SCHEDULE_MANUAL:
            self.next_settlement = None
        
        # Daily schedule
        elif self.schedule_type == SETTLEMENT_SCHEDULE_DAILY:
            base_date = self.last_settlement or now
            next_date = base_date + timedelta(days=1)
            
            # Apply time of day if specified
            if self.time_of_day:
                next_date = next_date.replace(
                    hour=self.time_of_day.hour,
                    minute=self.time_of_day.minute,
                    second=0,
                    microsecond=0
                )
            
            self.next_settlement = next_date
        
        # Weekly schedule
        elif self.schedule_type == SETTLEMENT_SCHEDULE_WEEKLY:
            if self.day_of_week is None:
                raise ValueError(_("Day of week must be specified for weekly schedules"))
            
            base_date = self.last_settlement or now
            days_ahead = self.day_of_week - base_date.weekday()
            
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            
            next_date = base_date + timedelta(days=days_ahead)
            
            # Apply time of day if specified
            if self.time_of_day:
                next_date = next_date.replace(
                    hour=self.time_of_day.hour,
                    minute=self.time_of_day.minute,
                    second=0,
                    microsecond=0
                )
            
            self.next_settlement = next_date
        
        # Monthly schedule
        elif self.schedule_type == SETTLEMENT_SCHEDULE_MONTHLY:
            if self.day_of_month is None:
                raise ValueError(_("Day of month must be specified for monthly schedules"))
            
            base_date = self.last_settlement or now
            
            # Try to set to the specified day of next month
            try:
                next_date = base_date.replace(
                    month=base_date.month + 1 if base_date.month < 12 else 1,
                    year=base_date.year if base_date.month < 12 else base_date.year + 1,
                    day=min(self.day_of_month, 28)  # Safe default
                )
            except ValueError:
                # Handle invalid dates (e.g., Feb 30)
                next_date = base_date.replace(
                    month=base_date.month + 1 if base_date.month < 12 else 1,
                    year=base_date.year if base_date.month < 12 else base_date.year + 1,
                    day=1
                )
            
            # Apply time of day if specified
            if self.time_of_day:
                next_date = next_date.replace(
                    hour=self.time_of_day.hour,
                    minute=self.time_of_day.minute,
                    second=0,
                    microsecond=0
                )
            
            self.next_settlement = next_date
        
        # Threshold-based schedules don't have automatic next settlement
        elif self.schedule_type == SETTLEMENT_SCHEDULE_THRESHOLD:
            self.next_settlement = None
        
        self.save(update_fields=['next_settlement'])
        return self
    
    @db_transaction.atomic
    def activate(self):
        """
        Activate the settlement schedule
        
        Returns:
            SettlementSchedule: Updated schedule instance
        """
        self.is_active = True
        
        # Calculate next settlement if not already set
        if not self.next_settlement and self.is_time_based:
            self.calculate_next_settlement()
        else:
            self.save(update_fields=['is_active'])
        
        return self
    
    @db_transaction.atomic
    def deactivate(self):
        """
        Deactivate the settlement schedule
        
        Returns:
            SettlementSchedule: Updated schedule instance
        """
        self.is_active = False
        self.save(update_fields=['is_active'])
        return self
    
    def save(self, *args, **kwargs):
        """
        Override save to calculate next settlement on creation
        
        Args:
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments
        """
        # Calculate next settlement for new active time-based schedules
        if not self.pk and self.is_active and self.is_time_based:
            super().save(*args, **kwargs)  # Save first to get an ID
            self.calculate_next_settlement()
        else:
            super().save(*args, **kwargs)