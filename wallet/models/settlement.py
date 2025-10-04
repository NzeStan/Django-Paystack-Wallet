from django.db import models
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField

from wallet.models.base import BaseModel
from wallet.constants import SETTLEMENT_STATUSES, SETTLEMENT_STATUS_PENDING
from wallet.settings import get_wallet_setting


class Settlement(BaseModel):
    """
    Settlement model for tracking wallet settlements to bank accounts
    """
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='settlements',
        verbose_name=_('Wallet')
    )
    bank_account = models.ForeignKey(
        'wallet.BankAccount',
        on_delete=models.SET_NULL,
        related_name='settlements',
        null=True,
        verbose_name=_('Bank account')
    )
    amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Amount')
    )
    fees = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Fees')
    )
    status = models.CharField(
        max_length=20,
        choices=SETTLEMENT_STATUSES,
        default=SETTLEMENT_STATUS_PENDING,
        verbose_name=_('Status')
    )
    reference = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_('Reference')
    )
    paystack_transfer_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Paystack transfer code')
    )
    paystack_transfer_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack transfer data')
    )
    reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Reason')
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_('Metadata')
    )
    transaction = models.OneToOneField(
        'wallet.Transaction',
        on_delete=models.SET_NULL,
        related_name='settlement',
        null=True,
        blank=True,
        verbose_name=_('Transaction')
    )
    settled_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('Settled at')
    )
    failure_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Failure reason')
    )
    
    class Meta:
        verbose_name = _('Settlement')
        verbose_name_plural = _('Settlements')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'status']),
            models.Index(fields=['reference']),
            models.Index(fields=['paystack_transfer_code']),
        ]
    
    def __str__(self):
        return f"Settlement {self.reference} - {self.amount} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        # Generate a reference if not provided
        if not self.reference:
            from wallet.utils.id_generators import generate_settlement_reference
            self.reference = generate_settlement_reference()
        super().save(*args, **kwargs)


class SettlementSchedule(BaseModel):
    """
    Settlement schedule model for automatically settling wallet funds
    """
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='settlement_schedules',
        verbose_name=_('Wallet')
    )
    bank_account = models.ForeignKey(
        'wallet.BankAccount',
        on_delete=models.CASCADE,
        related_name='settlement_schedules',
        verbose_name=_('Bank account')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    amount_threshold = MoneyField(
        max_digits=19,
        decimal_places=2,
        blank=True,
        null=True,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Amount threshold'),
        help_text=_('Settle when wallet balance reaches this amount')
    )
    schedule_type = models.CharField(
        max_length=20,
        choices=[
            ('daily', _('Daily')),
            ('weekly', _('Weekly')),
            ('monthly', _('Monthly')),
            ('threshold', _('Threshold')),
            ('manual', _('Manual')),
        ],
        default='manual',
        verbose_name=_('Schedule type')
    )
    day_of_week = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        choices=[
            (0, _('Monday')),
            (1, _('Tuesday')),
            (2, _('Wednesday')),
            (3, _('Thursday')),
            (4, _('Friday')),
            (5, _('Saturday')),
            (6, _('Sunday')),
        ],
        verbose_name=_('Day of week'),
        help_text=_('Day of week for weekly settlements')
    )
    day_of_month = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name=_('Day of month'),
        help_text=_('Day of month for monthly settlements (1-31)')
    )
    time_of_day = models.TimeField(
        blank=True,
        null=True,
        verbose_name=_('Time of day'),
        help_text=_('Time of day for the settlement')
    )
    last_settlement = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('Last settlement')
    )
    next_settlement = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('Next settlement')
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
        blank=True,
        null=True,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Maximum amount'),
        help_text=_('Maximum amount to settle, leave blank for no limit')
    )
    
    class Meta:
        verbose_name = _('Settlement schedule')
        verbose_name_plural = _('Settlement schedules')
        ordering = ['wallet', 'schedule_type']
    
    def __str__(self):
        return f"{self.wallet}'s {self.get_schedule_type_display()} settlement schedule"
    
    def calculate_next_settlement(self):
        """Calculate and set the next settlement date based on the schedule type"""
        import datetime
        from django.utils import timezone
        
        now = timezone.now()
        
        if self.schedule_type == 'daily':
            if self.time_of_day:
                next_time = datetime.datetime.combine(
                    now.date() + datetime.timedelta(days=1),
                    self.time_of_day,
                    tzinfo=timezone.get_current_timezone()
                )
            else:
                next_time = now.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + datetime.timedelta(days=1)
                
        elif self.schedule_type == 'weekly':
            days_ahead = self.day_of_week - now.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
                
            next_date = now.date() + datetime.timedelta(days=days_ahead)
            
            if self.time_of_day:
                next_time = datetime.datetime.combine(
                    next_date,
                    self.time_of_day,
                    tzinfo=timezone.get_current_timezone()
                )
            else:
                next_time = datetime.datetime.combine(
                    next_date,
                    datetime.time(0, 0),
                    tzinfo=timezone.get_current_timezone()
                )
                
        elif self.schedule_type == 'monthly':
            if self.day_of_month:
                day = min(self.day_of_month, 28)  # Ensure it works in February
                
                if now.day <= day:
                    next_month = now.month
                    next_year = now.year
                else:
                    if now.month == 12:
                        next_month = 1
                        next_year = now.year + 1
                    else:
                        next_month = now.month + 1
                        next_year = now.year
                        
                next_date = datetime.date(next_year, next_month, day)
                
                if self.time_of_day:
                    next_time = datetime.datetime.combine(
                        next_date,
                        self.time_of_day,
                        tzinfo=timezone.get_current_timezone()
                    )
                else:
                    next_time = datetime.datetime.combine(
                        next_date,
                        datetime.time(0, 0),
                        tzinfo=timezone.get_current_timezone()
                    )
            else:
                next_time = None
        else:
            # No automatic schedule or threshold based
            next_time = None
            
        self.next_settlement = next_time
        self.save(update_fields=['next_settlement', 'updated_at'])