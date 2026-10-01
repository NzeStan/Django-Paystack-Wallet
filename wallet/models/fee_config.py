"""
Database-driven fee configuration.

Enable with ``WALLET_USE_DATABASE_FEE_CONFIG = True``. Configurations are
matched most-specific first:

1. wallet-specific + payment channel
2. wallet-specific (any channel)
3. global + payment channel
4. global (any channel)

Within each level the highest ``priority`` wins. Only active configurations
inside their ``valid_from`` / ``valid_until`` window are considered. When no
configuration matches, the settings-based pricing is used.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.constants import (
    FEE_BEARER_SPLIT,
    FEE_BEARERS,
    FEE_TYPE_FLAT,
    FEE_TYPE_HYBRID,
    FEE_TYPE_PERCENTAGE,
    FEE_TYPE_TIERED,
    FEE_TYPES,
    PAYMENT_CHANNELS,
    TRANSACTION_TYPES,
)
from wallet.models.base import BaseModel
from wallet.models.fields import WalletMoneyField


class FeeConfigurationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def currently_valid(self):
        now = timezone.now()
        return self.filter(
            is_active=True,
        ).filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=now),
            Q(valid_until__isnull=True) | Q(valid_until__gte=now),
        )

    def for_wallet(self, wallet):
        return self.currently_valid().filter(Q(wallet=wallet) | Q(wallet__isnull=True))


class FeeConfigurationManager(models.Manager.from_queryset(FeeConfigurationQuerySet)):
    def for_transaction(self, wallet, transaction_type, payment_channel=None):
        """Return the best matching configuration, or None."""
        base = self.get_queryset().currently_valid().filter(transaction_type=transaction_type).order_by(
            '-priority', '-created_at'
        )
        candidates = []
        if wallet is not None:
            if payment_channel:
                candidates.append(base.filter(wallet=wallet, payment_channel=payment_channel))
            candidates.append(base.filter(wallet=wallet, payment_channel__isnull=True))
        if payment_channel:
            candidates.append(base.filter(wallet__isnull=True, payment_channel=payment_channel))
        candidates.append(base.filter(wallet__isnull=True, payment_channel__isnull=True))

        for queryset in candidates:
            match = queryset.prefetch_related('tiers').first()
            if match:
                return match
        return None


class FeeConfiguration(BaseModel):
    wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.CASCADE, related_name='fee_configurations', null=True, blank=True,
        verbose_name=_('Wallet'), help_text=_('Leave blank for a global configuration'),
    )
    name = models.CharField(max_length=200, verbose_name=_('Name'))
    description = models.TextField(blank=True, default='', verbose_name=_('Description'))
    transaction_type = models.CharField(
        max_length=20, choices=TRANSACTION_TYPES, db_index=True, verbose_name=_('Transaction type'),
    )
    payment_channel = models.CharField(
        max_length=20, choices=PAYMENT_CHANNELS, blank=True, null=True, verbose_name=_('Payment channel'),
        help_text=_('Optional: only apply to this deposit channel'),
    )
    fee_type = models.CharField(max_length=20, choices=FEE_TYPES, default=FEE_TYPE_HYBRID, verbose_name=_('Fee type'))
    percentage_fee = models.DecimalField(
        max_digits=6, decimal_places=3, default=0, verbose_name=_('Percentage fee'),
        help_text=_('e.g. 1.5 for 1.5%'),
    )
    flat_fee = WalletMoneyField(default=0, verbose_name=_('Flat fee'))
    fee_cap = WalletMoneyField(null=True, blank=True, verbose_name=_('Fee cap'))
    minimum_fee = WalletMoneyField(null=True, blank=True, verbose_name=_('Minimum fee'))
    waiver_threshold = WalletMoneyField(
        null=True, blank=True, verbose_name=_('Flat fee waiver threshold'),
        help_text=_('The flat fee is waived for amounts below this'),
    )
    fee_bearer = models.CharField(
        max_length=20, choices=FEE_BEARERS, blank=True, null=True, verbose_name=_('Fee bearer'),
        help_text=_('Leave blank to use the settings default'),
    )
    customer_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=50, verbose_name=_('Customer share %'),
    )
    merchant_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=50, verbose_name=_('Merchant share %'),
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_('Is active'))
    priority = models.IntegerField(default=0, verbose_name=_('Priority'), help_text=_('Higher wins'))
    valid_from = models.DateTimeField(null=True, blank=True, verbose_name=_('Valid from'))
    valid_until = models.DateTimeField(null=True, blank=True, verbose_name=_('Valid until'))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_('Metadata'))

    objects = FeeConfigurationManager()

    class Meta:
        verbose_name = _('Fee configuration')
        verbose_name_plural = _('Fee configurations')
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['transaction_type', 'payment_channel'], name='fee_txn_channel_idx'),
        ]

    def __str__(self):
        scope = str(self.wallet_id) if self.wallet_id else 'Global'
        return f"{self.name} ({scope} - {self.get_transaction_type_display()})"

    def clean(self):
        errors = {}
        if self.fee_bearer == FEE_BEARER_SPLIT and (self.customer_percentage + self.merchant_percentage) != 100:
            errors['customer_percentage'] = _('Customer and merchant shares must add up to 100')
        if self.fee_type == FEE_TYPE_PERCENTAGE and not self.percentage_fee:
            errors['percentage_fee'] = _('Required for percentage fees')
        if self.fee_type == FEE_TYPE_FLAT and (not self.flat_fee or self.flat_fee.amount <= 0):
            errors['flat_fee'] = _('Required for flat fees')
        if self.percentage_fee is not None and not 0 <= self.percentage_fee < 100:
            errors['percentage_fee'] = _('Must be between 0 and 100')
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            errors['valid_until'] = _('Must be after valid from')
        if errors:
            raise ValidationError(errors)

    def calculate_fee(self, amount):
        """Return the fee (Decimal, 2 d.p.) this configuration charges on ``amount`` (Decimal or Money)."""
        from wallet.utils.money import quantize

        value = Decimal(str(getattr(amount, 'amount', amount)))
        percentage = Decimal(str(self.percentage_fee or 0)) / 100
        flat = self.flat_fee.amount if self.flat_fee else Decimal('0')
        waived = bool(self.waiver_threshold and value < self.waiver_threshold.amount)

        if self.fee_type == FEE_TYPE_TIERED:
            tier = next((t for t in self.tiers.all() if t.applies_to(value)), None)
            fee = tier.calculate(value) if tier else Decimal('0')
        elif self.fee_type == FEE_TYPE_PERCENTAGE:
            fee = value * percentage
        elif self.fee_type == FEE_TYPE_FLAT:
            fee = Decimal('0') if waived else flat
        else:
            fee = value * percentage + (Decimal('0') if waived else flat)

        if self.minimum_fee and fee < self.minimum_fee.amount:
            fee = self.minimum_fee.amount
        if self.fee_cap and fee > self.fee_cap.amount:
            fee = self.fee_cap.amount
        return quantize(max(fee, Decimal('0')))


class FeeTier(BaseModel):
    """An amount band for ``tiered`` fee configurations, e.g. up to 5,000 -> NGN 10."""

    configuration = models.ForeignKey(
        FeeConfiguration, on_delete=models.CASCADE, related_name='tiers', verbose_name=_('Configuration'),
    )
    min_amount = WalletMoneyField(default=0, verbose_name=_('Minimum amount'), help_text=_('Inclusive'))
    max_amount = WalletMoneyField(
        null=True, blank=True, verbose_name=_('Maximum amount'), help_text=_('Inclusive; blank = unlimited'),
    )
    fee_amount = WalletMoneyField(default=0, verbose_name=_('Flat fee'))
    percentage_fee = models.DecimalField(
        max_digits=6, decimal_places=3, default=0, verbose_name=_('Percentage fee'),
    )

    class Meta:
        verbose_name = _('Fee tier')
        verbose_name_plural = _('Fee tiers')
        ordering = ['min_amount']

    def __str__(self):
        upper = self.max_amount.amount if self.max_amount else 'unlimited'
        return f"{self.min_amount.amount} - {upper}: {self.fee_amount.amount} + {self.percentage_fee}%"

    def applies_to(self, amount):
        value = Decimal(str(getattr(amount, 'amount', amount)))
        if value < self.min_amount.amount:
            return False
        return not (self.max_amount and value > self.max_amount.amount)

    def calculate(self, amount):
        value = Decimal(str(getattr(amount, 'amount', amount)))
        return self.fee_amount.amount + value * Decimal(str(self.percentage_fee or 0)) / 100


class FeeHistory(BaseModel):
    """Audit trail of how each transaction's fee was calculated."""

    transaction = models.OneToOneField(
        'wallet.Transaction', on_delete=models.CASCADE, related_name='fee_history', verbose_name=_('Transaction'),
    )
    configuration_used = models.ForeignKey(
        FeeConfiguration, on_delete=models.SET_NULL, null=True, blank=True, related_name='fee_histories',
        verbose_name=_('Configuration used'),
    )
    calculation_method = models.CharField(max_length=50, verbose_name=_('Calculation method'))
    original_amount = WalletMoneyField(verbose_name=_('Original amount'))
    calculated_fee = WalletMoneyField(verbose_name=_('Calculated fee'))
    fee_bearer = models.CharField(max_length=20, choices=FEE_BEARERS, verbose_name=_('Fee bearer'))
    calculation_details = models.JSONField(default=dict, verbose_name=_('Calculation details'))

    class Meta:
        verbose_name = _('Fee history')
        verbose_name_plural = _('Fee histories')
        ordering = ['-created_at']

    def __str__(self):
        return f"Fee history for {self.transaction.reference}"
