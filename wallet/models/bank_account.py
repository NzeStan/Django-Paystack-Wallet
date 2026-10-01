from django.db import models, transaction
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _

from wallet.constants import (
    BANK_ACCOUNT_TYPE_SAVINGS,
    BANK_ACCOUNT_TYPES,
    RECIPIENT_TYPE_NUBAN,
    RECIPIENT_TYPES,
)
from wallet.models.base import BaseModel


class BankQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def by_country(self, country):
        return self.filter(country__iexact=country)

    def by_currency(self, currency):
        return self.filter(currency__iexact=currency)

    def search(self, query):
        return self.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(slug__icontains=query))


class BankManager(models.Manager.from_queryset(BankQuerySet)):
    def get_by_code(self, code, currency=None):
        queryset = self.filter(code=code)
        if currency:
            queryset = queryset.filter(currency=currency)
        return queryset.first()


class Bank(BaseModel):
    """A bank (or mobile money operator) supported by Paystack. Populate with ``manage.py sync_banks``."""

    name = models.CharField(max_length=255, verbose_name=_('Name'))
    code = models.CharField(max_length=20, db_index=True, verbose_name=_('Code'))
    slug = models.SlugField(max_length=255, blank=True, default='', verbose_name=_('Slug'))
    country = models.CharField(max_length=50, default='Nigeria', verbose_name=_('Country'))
    currency = models.CharField(max_length=3, default='NGN', db_index=True, verbose_name=_('Currency'))
    type = models.CharField(max_length=50, blank=True, default='', verbose_name=_('Type'))
    paystack_id = models.BigIntegerField(null=True, blank=True)
    supports_transfer = models.BooleanField(default=True, verbose_name=_('Supports transfers'))
    pay_with_bank = models.BooleanField(default=False, verbose_name=_('Supports pay with bank'))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_('Is active'))
    paystack_data = models.JSONField(blank=True, null=True)

    objects = BankManager()

    class Meta:
        verbose_name = _('Bank')
        verbose_name_plural = _('Banks')
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['code', 'currency', 'type'], name='bank_unique_code_currency_type'),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class BankAccountQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def verified(self):
        return self.filter(is_verified=True)

    def unverified(self):
        return self.filter(is_verified=False)

    def defaults(self):
        return self.filter(is_default=True)

    def by_wallet(self, wallet):
        return self.filter(wallet=wallet)

    def by_bank(self, bank):
        return self.filter(bank=bank)

    def with_bank_details(self):
        return self.select_related('bank')

    def with_full_details(self):
        return self.select_related('wallet', 'wallet__user', 'bank')

    def with_transaction_count(self):
        return self.annotate(transaction_count=Count('transactions'))

    def search(self, query):
        return self.filter(
            Q(account_name__icontains=query) | Q(account_number__icontains=query) | Q(bank__name__icontains=query)
        )


class BankAccountManager(models.Manager.from_queryset(BankAccountQuerySet)):
    def for_wallet(self, wallet):
        return self.get_queryset().by_wallet(wallet)


class BankAccount(BaseModel):
    """
    A payout destination (bank account or mobile money wallet) linked to a
    Paystack transfer recipient.
    """

    wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.CASCADE, related_name='bank_accounts', verbose_name=_('Wallet'),
    )
    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, related_name='bank_accounts', verbose_name=_('Bank'))
    account_number = models.CharField(max_length=20, verbose_name=_('Account number'))
    account_name = models.CharField(max_length=255, verbose_name=_('Account name'))
    account_type = models.CharField(
        max_length=20, choices=BANK_ACCOUNT_TYPES, default=BANK_ACCOUNT_TYPE_SAVINGS, verbose_name=_('Account type'),
    )
    recipient_type = models.CharField(
        max_length=20, choices=RECIPIENT_TYPES, default=RECIPIENT_TYPE_NUBAN, verbose_name=_('Recipient type'),
    )
    currency = models.CharField(max_length=3, default='NGN', verbose_name=_('Currency'))
    bvn = models.CharField(max_length=11, blank=True, default='', verbose_name=_('BVN'))

    is_verified = models.BooleanField(default=False, verbose_name=_('Is verified'))
    is_default = models.BooleanField(default=False, verbose_name=_('Is default'))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_('Is active'))

    paystack_recipient_code = models.CharField(
        max_length=100, blank=True, null=True, db_index=True, verbose_name=_('Paystack recipient code'),
    )
    paystack_recipient_id = models.BigIntegerField(null=True, blank=True)
    paystack_data = models.JSONField(blank=True, null=True)

    objects = BankAccountManager()

    class Meta:
        verbose_name = _('Bank account')
        verbose_name_plural = _('Bank accounts')
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['wallet', 'bank', 'account_number'], name='bankaccount_unique_per_wallet',
            ),
        ]
        indexes = [
            models.Index(fields=['wallet', 'is_active'], name='bankacct_wallet_active_idx'),
        ]

    def __str__(self):
        return f"{self.account_name} - {self.bank.name} ({self.masked_account_number})"

    def save(self, *args, **kwargs):
        if self.is_default:
            BankAccount.objects.filter(wallet_id=self.wallet_id, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        super().save(*args, **kwargs)

    @transaction.atomic
    def set_as_default(self):
        BankAccount.objects.filter(wallet_id=self.wallet_id, is_default=True).exclude(pk=self.pk).update(
            is_default=False
        )
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])

    @transaction.atomic
    def remove(self):
        was_default = self.is_default
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
        if was_default:
            replacement = BankAccount.objects.filter(
                wallet_id=self.wallet_id, is_active=True
            ).exclude(pk=self.pk).first()
            if replacement:
                replacement.set_as_default()

    def verify(self):
        self.is_verified = True
        self.save(update_fields=['is_verified', 'updated_at'])

    def activate(self):
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])

    def deactivate(self):
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])

    @property
    def masked_account_number(self):
        if len(self.account_number) > 4:
            return f"{'*' * (len(self.account_number) - 4)}{self.account_number[-4:]}"
        return self.account_number

    @property
    def can_receive_transfers(self):
        return self.is_active and bool(self.paystack_recipient_code)

    @property
    def display_name(self):
        return f"{self.bank.name} - {self.masked_account_number} ({self.account_name})"
