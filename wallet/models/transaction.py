from django.db import models
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField

from wallet.models.base import BaseModel
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPES, TRANSACTION_STATUSES, PAYMENT_METHODS,
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_STATUS_PENDING
)


class Transaction(BaseModel):
    """
    Transaction model for recording all financial activities
    """
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='transactions',
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
        verbose_name=_('Reference'),
        help_text=_('Unique reference for this transaction')
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        default=TRANSACTION_TYPE_DEPOSIT,
        verbose_name=_('Transaction type')
    )
    status = models.CharField(
        max_length=20,
        choices=TRANSACTION_STATUSES,
        default=TRANSACTION_STATUS_PENDING,
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
    paystack_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Paystack reference')
    )
    paystack_response = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack response')
    )
    recipient_wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.SET_NULL,
        related_name='received_transactions',
        blank=True,
        null=True,
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
    fees = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Fees')
    )
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
        verbose_name=_('Completed at')
    )
    failed_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Failed reason')
    )
    
    class Meta:
        verbose_name = _('Transaction')
        verbose_name_plural = _('Transactions')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'created_at']),
            models.Index(fields=['transaction_type', 'status']),
            models.Index(fields=['paystack_reference']),
        ]
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        # Generate a reference if not provided
        if not self.reference:
            from wallet.utils.id_generators import generate_transaction_reference
            self.reference = generate_transaction_reference()
        super().save(*args, **kwargs)
    
    @property
    def is_completed(self):
        """Check if the transaction is completed (success or failed)"""
        from wallet.constants import TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED
        return self.status in [TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED]
    