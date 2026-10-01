from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.constants import CARD_TYPE_OTHER, CARD_TYPES
from wallet.models.base import BaseModel


def normalize_card_type(value):
    """Paystack returns values like 'visa ', 'mastercard', 'visa DEBIT' - map to our choices."""
    if not value:
        return CARD_TYPE_OTHER
    first = str(value).strip().lower().split()[0] if str(value).strip() else ''
    known = {choice for choice, _label in CARD_TYPES}
    if first in ('american', 'americanexpress', 'american_express'):
        return 'amex'
    return first if first in known else CARD_TYPE_OTHER


class CardQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def defaults(self):
        return self.filter(is_default=True)

    def expired(self):
        now = timezone.now()
        return self.filter(
            Q(expiry_year__lt=str(now.year))
            | Q(expiry_year=str(now.year), expiry_month__lt=f'{now.month:02d}')
        )

    def not_expired(self):
        now = timezone.now()
        return self.filter(
            Q(expiry_year__gt=str(now.year))
            | Q(expiry_year=str(now.year), expiry_month__gte=f'{now.month:02d}')
        )

    def by_wallet(self, wallet):
        return self.filter(wallet=wallet)

    def with_wallet_details(self):
        return self.select_related('wallet', 'wallet__user')

    def with_transaction_count(self):
        return self.annotate(transaction_count=Count('transactions'))

    def search(self, query):
        return self.filter(
            Q(last_four__icontains=query) | Q(card_holder_name__icontains=query)
            | Q(card_type__icontains=query) | Q(bank__icontains=query)
        )


class CardManager(models.Manager.from_queryset(CardQuerySet)):
    def for_wallet(self, wallet):
        return self.get_queryset().by_wallet(wallet)

    def get_by_authorization_code(self, authorization_code):
        return self.get_queryset().filter(paystack_authorization_code=authorization_code).first()


class Card(BaseModel):
    """
    A reusable Paystack card authorization. Card numbers and CVVs are never stored.
    """

    wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.CASCADE, related_name='cards', verbose_name=_('Wallet'),
    )
    card_type = models.CharField(
        max_length=20, choices=CARD_TYPES, default=CARD_TYPE_OTHER, verbose_name=_('Card type'),
    )
    last_four = models.CharField(max_length=4, verbose_name=_('Last four digits'))
    expiry_month = models.CharField(max_length=2, verbose_name=_('Expiry month'))
    expiry_year = models.CharField(max_length=4, verbose_name=_('Expiry year'))
    bin = models.CharField(max_length=8, blank=True, default='', verbose_name=_('BIN'))
    bank = models.CharField(max_length=100, blank=True, default='', verbose_name=_('Issuing bank'))
    country_code = models.CharField(max_length=2, blank=True, default='', verbose_name=_('Country code'))
    card_holder_name = models.CharField(max_length=255, blank=True, default='', verbose_name=_('Card holder name'))
    email = models.EmailField(blank=True, default='', verbose_name=_('Email'))

    is_default = models.BooleanField(default=False, verbose_name=_('Is default'))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_('Is active'))

    paystack_authorization_code = models.CharField(max_length=100, db_index=True, verbose_name=_('Authorization code'))
    paystack_authorization_signature = models.CharField(
        max_length=255, blank=True, default='', db_index=True, verbose_name=_('Card signature'),
        help_text=_('Identifies the same physical card across authorizations'),
    )
    paystack_card_data = models.JSONField(blank=True, null=True, verbose_name=_('Paystack authorization data'))

    objects = CardManager()

    class Meta:
        verbose_name = _('Card')
        verbose_name_plural = _('Cards')
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['wallet', 'paystack_authorization_code'], name='card_unique_authorization_per_wallet',
            ),
        ]
        indexes = [
            models.Index(fields=['wallet', 'is_active'], name='card_wallet_active_idx'),
        ]

    def __str__(self):
        return f"{self.get_card_type_display()} **** {self.last_four}"

    def save(self, *args, **kwargs):
        if self.is_default:
            Card.objects.filter(wallet_id=self.wallet_id, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @transaction.atomic
    def set_as_default(self):
        Card.objects.filter(wallet_id=self.wallet_id, is_default=True).exclude(pk=self.pk).update(is_default=False)
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])

    @transaction.atomic
    def remove(self):
        """Soft-delete the card and promote another active card to default."""
        was_default = self.is_default
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
        if was_default:
            replacement = Card.objects.filter(wallet_id=self.wallet_id, is_active=True).exclude(pk=self.pk).first()
            if replacement:
                replacement.set_as_default()

    def activate(self):
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])

    def deactivate(self):
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])

    @property
    def is_expired(self):
        try:
            year, month = int(self.expiry_year), int(self.expiry_month)
        except (TypeError, ValueError):
            return False
        now = timezone.now()
        return year < now.year or (year == now.year and month < now.month)

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    @property
    def masked_pan(self):
        prefix = self.bin[:6] if self.bin else '****'
        return f"{prefix} **** **** {self.last_four}"

    @property
    def expiry(self):
        return f"{self.expiry_month}/{self.expiry_year}"

    @property
    def display_name(self):
        return f"{self.get_card_type_display()} **** {self.last_four} ({self.expiry})"
