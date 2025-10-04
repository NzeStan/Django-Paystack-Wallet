from django.db import models
from django.utils.translation import gettext_lazy as _

from wallet.models.base import BaseModel
from wallet.constants import BANK_ACCOUNT_TYPES, BANK_ACCOUNT_TYPE_SAVINGS


class Bank(BaseModel):
    """
    Bank model for storing bank information from Paystack
    """
    name = models.CharField(
        max_length=255,
        verbose_name=_('Name')
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_('Code')
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        verbose_name=_('Slug')
    )
    country = models.CharField(
        max_length=2,
        default='NG',
        verbose_name=_('Country')
    )
    currency = models.CharField(
        max_length=3,
        default='NGN',
        verbose_name=_('Currency')
    )
    type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_('Type')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    paystack_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack data')
    )
    
    class Meta:
        verbose_name = _('Bank')
        verbose_name_plural = _('Banks')
        ordering = ['name']
    
    def __str__(self):
        return self.name


class BankAccount(BaseModel):
    """
    Bank account model for storing user bank account information
    """
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        verbose_name=_('Wallet')
    )
    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,
        related_name='bank_accounts',
        verbose_name=_('Bank')
    )
    account_number = models.CharField(
        max_length=20,
        verbose_name=_('Account number')
    )
    account_name = models.CharField(
        max_length=255,
        verbose_name=_('Account name')
    )
    account_type = models.CharField(
        max_length=20,
        choices=BANK_ACCOUNT_TYPES,
        default=BANK_ACCOUNT_TYPE_SAVINGS,
        verbose_name=_('Account type')
    )
    bvn = models.CharField(
        max_length=11,
        blank=True,
        null=True,
        verbose_name=_('BVN'),
        help_text=_('Bank Verification Number')
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name=_('Is verified')
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_('Is default')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    paystack_recipient_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Paystack recipient code')
    )
    paystack_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack data')
    )
    
    class Meta:
        verbose_name = _('Bank account')
        verbose_name_plural = _('Bank accounts')
        ordering = ['-is_default', '-created_at']
        unique_together = ('wallet', 'bank', 'account_number')
        indexes = [
            models.Index(fields=['wallet', 'is_default']),
            models.Index(fields=['paystack_recipient_code']),
        ]
    
    def __str__(self):
        return f"{self.account_name} - {self.bank.name} ({self.account_number})"
    
    def save(self, *args, **kwargs):
        # If this account is being set as default, unset any other default accounts for this wallet
        if self.is_default:
            BankAccount.objects.filter(wallet=self.wallet, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
    
    def set_as_default(self):
        """Set this account as the default account for the wallet"""
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])
    
    def remove(self):
        """Mark the account as inactive instead of deleting it"""
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
        
        # Set another account as default if this was the default
        if not self.is_active and self.wallet.bank_accounts.filter(is_active=True).exists():
            new_default = self.wallet.bank_accounts.filter(is_active=True).first()
            new_default.set_as_default()