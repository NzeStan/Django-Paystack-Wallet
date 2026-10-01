import calendar
from datetime import datetime, timedelta

from django.db import models
from django.db.models import Avg, Count, Max, Min, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.constants import (
    SETTLEMENT_SCHEDULE_DAILY,
    SETTLEMENT_SCHEDULE_MANUAL,
    SETTLEMENT_SCHEDULE_MONTHLY,
    SETTLEMENT_SCHEDULE_THRESHOLD,
    SETTLEMENT_SCHEDULE_TYPES,
    SETTLEMENT_SCHEDULE_WEEKLY,
    SETTLEMENT_STATUS_FAILED,
    SETTLEMENT_STATUS_PENDING,
    SETTLEMENT_STATUS_PROCESSING,
    SETTLEMENT_STATUS_SUCCESS,
    SETTLEMENT_STATUSES,
)
from wallet.models.base import BaseModel
from wallet.models.fields import WalletMoneyField


class SettlementQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status=SETTLEMENT_STATUS_PENDING)

    def processing(self):
        return self.filter(status=SETTLEMENT_STATUS_PROCESSING)

    def successful(self):
        return self.filter(status=SETTLEMENT_STATUS_SUCCESS)

    def failed(self):
        return self.filter(status=SETTLEMENT_STATUS_FAILED)

    def completed(self):
        return self.filter(status__in=[SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED])

    def by_wallet(self, wallet):
        return self.filter(wallet=wallet)

    def by_bank_account(self, bank_account):
        return self.filter(bank_account=bank_account)

    def with_full_details(self):
        return self.select_related('wallet', 'wallet__user', 'bank_account', 'bank_account__bank', 'transaction')

    def recent(self, days=30):
        return self.filter(created_at__gte=timezone.now() - timedelta(days=days))

    def in_date_range(self, start_date=None, end_date=None):
        queryset = self
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        return queryset

    def with_statistics(self):
        return self.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            average_amount=Avg('amount'),
            min_amount=Min('amount'),
            max_amount=Max('amount'),
            total_fees=Sum('fees'),
        )


class SettlementManager(models.Manager.from_queryset(SettlementQuerySet)):
    def for_wallet(self, wallet):
        return self.get_queryset().by_wallet(wallet)


class Settlement(BaseModel):
    """
    A payout of wallet funds to a bank account (manual or scheduled).

    The money movement itself is an ordinary withdrawal :class:`Transaction`
    (``settlement.transaction``); this model adds payout bookkeeping on top.
    """

    wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.CASCADE, related_name='settlements', verbose_name=_('Wallet'),
    )
    bank_account = models.ForeignKey(
        'wallet.BankAccount', on_delete=models.SET_NULL, related_name='settlements', null=True,
        verbose_name=_('Bank account'),
    )
    schedule = models.ForeignKey(
        'wallet.SettlementSchedule', on_delete=models.SET_NULL, related_name='settlements', null=True, blank=True,
    )
    amount = WalletMoneyField(verbose_name=_('Amount'))
    fees = WalletMoneyField(default=0, verbose_name=_('Fees'))
    status = models.CharField(
        max_length=20, choices=SETTLEMENT_STATUSES, default=SETTLEMENT_STATUS_PENDING, db_index=True,
        verbose_name=_('Status'),
    )
    reference = models.CharField(max_length=100, unique=True, verbose_name=_('Reference'))
    paystack_transfer_code = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    paystack_transfer_data = models.JSONField(blank=True, null=True)
    reason = models.TextField(blank=True, default='', verbose_name=_('Reason'))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_('Metadata'))
    transaction = models.OneToOneField(
        'wallet.Transaction', on_delete=models.SET_NULL, related_name='settlement', null=True, blank=True,
        verbose_name=_('Transaction'),
    )
    settled_at = models.DateTimeField(blank=True, null=True, verbose_name=_('Settled at'))
    failure_reason = models.TextField(blank=True, default='', verbose_name=_('Failure reason'))

    objects = SettlementManager()

    class Meta:
        verbose_name = _('Settlement')
        verbose_name_plural = _('Settlements')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'status'], name='settlement_wallet_status_idx'),
        ]

    def __str__(self):
        return f"Settlement {self.reference} - {self.amount} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.reference:
            from wallet.utils.id_generators import generate_settlement_reference
            self.reference = generate_settlement_reference()
        super().save(*args, **kwargs)

    @property
    def is_pending(self):
        return self.status == SETTLEMENT_STATUS_PENDING

    @property
    def is_processing(self):
        return self.status == SETTLEMENT_STATUS_PROCESSING

    @property
    def is_successful(self):
        return self.status == SETTLEMENT_STATUS_SUCCESS

    @property
    def is_failed(self):
        return self.status == SETTLEMENT_STATUS_FAILED

    @property
    def is_completed(self):
        return self.status in (SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED)

    @property
    def net_amount(self):
        return self.amount - self.fees

    @property
    def processing_time(self):
        return self.settled_at - self.created_at if self.settled_at else None

    @property
    def requires_otp(self):
        return bool(self.transaction and self.transaction.requires_otp)

    def mark_as_processing(self):
        self.status = SETTLEMENT_STATUS_PROCESSING
        self.save(update_fields=['status', 'updated_at'])
        return self

    def mark_as_success(self, paystack_data=None):
        self.status = SETTLEMENT_STATUS_SUCCESS
        self.settled_at = timezone.now()
        if paystack_data:
            self.paystack_transfer_data = paystack_data
        self.save(update_fields=['status', 'settled_at', 'paystack_transfer_data', 'updated_at'])
        return self

    def mark_as_failed(self, reason=None, paystack_data=None):
        self.status = SETTLEMENT_STATUS_FAILED
        self.failure_reason = str(reason or '')
        if paystack_data:
            self.paystack_transfer_data = paystack_data
        self.save(update_fields=['status', 'failure_reason', 'paystack_transfer_data', 'updated_at'])
        return self


class SettlementScheduleQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def by_wallet(self, wallet):
        return self.filter(wallet=wallet)

    def by_schedule_type(self, schedule_type):
        return self.filter(schedule_type=schedule_type)

    def due_now(self):
        return self.filter(
            is_active=True, next_settlement__lte=timezone.now(),
        ).exclude(schedule_type__in=[SETTLEMENT_SCHEDULE_MANUAL, SETTLEMENT_SCHEDULE_THRESHOLD])

    def threshold_based(self):
        return self.filter(
            is_active=True, schedule_type=SETTLEMENT_SCHEDULE_THRESHOLD, amount_threshold__isnull=False,
        )

    def with_full_details(self):
        return self.select_related('wallet', 'wallet__user', 'bank_account', 'bank_account__bank')


class SettlementScheduleManager(models.Manager.from_queryset(SettlementScheduleQuerySet)):
    def for_wallet(self, wallet):
        return self.get_queryset().by_wallet(wallet)


class SettlementSchedule(BaseModel):
    """
    Rules for automatic payouts.

    * daily / weekly / monthly - pay out on a timetable (run ``process_settlements``
      periodically, or the Celery beat task ``wallet.tasks.process_due_settlements_task``)
    * threshold - pay out whatever is above ``amount_threshold`` as soon as the
      balance crosses it (requires ``WALLET_AUTO_SETTLEMENT = True``)
    """

    wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.CASCADE, related_name='settlement_schedules', verbose_name=_('Wallet'),
    )
    bank_account = models.ForeignKey(
        'wallet.BankAccount', on_delete=models.CASCADE, related_name='settlement_schedules',
        verbose_name=_('Bank account'),
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_('Is active'))
    schedule_type = models.CharField(
        max_length=20, choices=SETTLEMENT_SCHEDULE_TYPES, default=SETTLEMENT_SCHEDULE_MANUAL,
        verbose_name=_('Schedule type'),
    )
    amount_threshold = WalletMoneyField(null=True, blank=True, verbose_name=_('Amount threshold'))
    minimum_amount = WalletMoneyField(default=0, verbose_name=_('Minimum amount'))
    maximum_amount = WalletMoneyField(null=True, blank=True, verbose_name=_('Maximum amount'))
    day_of_week = models.PositiveSmallIntegerField(
        blank=True, null=True, verbose_name=_('Day of week'), help_text=_('0 = Monday ... 6 = Sunday'),
    )
    day_of_month = models.PositiveSmallIntegerField(
        blank=True, null=True, verbose_name=_('Day of month'),
        help_text=_('1-31; short months use their last day'),
    )
    time_of_day = models.TimeField(blank=True, null=True, verbose_name=_('Time of day'))
    last_settlement = models.DateTimeField(blank=True, null=True, verbose_name=_('Last settlement'))
    next_settlement = models.DateTimeField(blank=True, null=True, db_index=True, verbose_name=_('Next settlement'))

    objects = SettlementScheduleManager()

    class Meta:
        verbose_name = _('Settlement schedule')
        verbose_name_plural = _('Settlement schedules')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.wallet} - {self.get_schedule_type_display()}"

    @property
    def is_due(self):
        return bool(self.is_active and self.next_settlement and timezone.now() >= self.next_settlement)

    @property
    def is_threshold_based(self):
        return self.schedule_type == SETTLEMENT_SCHEDULE_THRESHOLD

    @property
    def is_time_based(self):
        return self.schedule_type in (SETTLEMENT_SCHEDULE_DAILY, SETTLEMENT_SCHEDULE_WEEKLY, SETTLEMENT_SCHEDULE_MONTHLY)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.schedule_type == SETTLEMENT_SCHEDULE_WEEKLY and self.day_of_week is None:
            raise ValidationError({'day_of_week': _('Required for weekly schedules')})
        if self.day_of_week is not None and not 0 <= self.day_of_week <= 6:
            raise ValidationError({'day_of_week': _('Must be between 0 and 6')})
        if self.schedule_type == SETTLEMENT_SCHEDULE_MONTHLY and not self.day_of_month:
            raise ValidationError({'day_of_month': _('Required for monthly schedules')})
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 31:
            raise ValidationError({'day_of_month': _('Must be between 1 and 31')})
        if self.schedule_type == SETTLEMENT_SCHEDULE_THRESHOLD and self.amount_threshold is None:
            raise ValidationError({'amount_threshold': _('Required for threshold schedules')})

    def compute_next_settlement(self, after=None):
        """Return the next run time strictly after ``after`` (default: now), or None."""
        if not self.is_time_based:
            return None

        now = timezone.localtime(after or timezone.now())
        hour, minute = (self.time_of_day.hour, self.time_of_day.minute) if self.time_of_day else (0, 0)

        def at(day):
            return now.replace(year=day.year, month=day.month, day=day.day, hour=hour, minute=minute,
                               second=0, microsecond=0)

        if self.schedule_type == SETTLEMENT_SCHEDULE_DAILY:
            candidate = at(now)
            return candidate if candidate > now else at(now + timedelta(days=1))

        if self.schedule_type == SETTLEMENT_SCHEDULE_WEEKLY:
            target = self.day_of_week if self.day_of_week is not None else 0
            days_ahead = (target - now.weekday()) % 7
            candidate = at(now + timedelta(days=days_ahead))
            return candidate if candidate > now else at(now + timedelta(days=days_ahead + 7))

        # Monthly
        wanted = self.day_of_month or 1

        def in_month(year, month):
            day = min(wanted, calendar.monthrange(year, month)[1])
            return at(datetime(year, month, day))

        candidate = in_month(now.year, now.month)
        if candidate > now:
            return candidate
        year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        return in_month(year, month)

    def calculate_next_settlement(self, save=True):
        self.next_settlement = self.compute_next_settlement()
        if save and self.pk:
            self.save(update_fields=['next_settlement', 'updated_at'])
        return self

    def activate(self):
        self.is_active = True
        self.next_settlement = self.compute_next_settlement()
        self.save(update_fields=['is_active', 'next_settlement', 'updated_at'])
        return self

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])
        return self

    def save(self, *args, **kwargs):
        if self.is_active and self.is_time_based and not self.next_settlement:
            self.next_settlement = self.compute_next_settlement()
        super().save(*args, **kwargs)
