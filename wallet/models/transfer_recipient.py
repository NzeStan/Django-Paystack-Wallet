from django.db import models
from django.utils.translation import gettext_lazy as _

from wallet.models.base import BaseModel


class TransferRecipient(BaseModel):
    """
    Transfer recipient model for storing recipient information for transfers
    """
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='transfer_recipients',
        verbose_name=_('Wallet')
    )
    recipient_code = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_('Recipient code')
    )
    type = models.CharField(
        max_length=20,
        verbose_name=_('Type'),
        help_text=_('Type of recipient (e.g., nuban, mobile_money)')
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_('Name')
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Description')
    )
    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_('Email')
    )
    account_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_('Account number')
    )
    bank_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_('Bank code')
    )
    bank_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('Bank name')
    )
    currency = models.CharField(
        max_length=3,
        default='NGN',
        verbose_name=_('Currency')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_('Metadata')
    )
    paystack_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack data')
    )
    
    class Meta:
        verbose_name = _('Transfer recipient')
        verbose_name_plural = _('Transfer recipients')
        ordering = ['name']
        indexes = [
            models.Index(fields=['recipient_code']),
            models.Index(fields=['wallet', 'is_active']),
        ]
    
    def __str__(self):
        bank_info = f" - {self.bank_name} ({self.account_number})" if self.bank_name else ""
        return f"{self.name}{bank_info}"
    
    def deactivate(self):
        """Deactivate this recipient"""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])