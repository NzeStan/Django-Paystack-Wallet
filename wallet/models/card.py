from django.db import models
from django.utils.translation import gettext_lazy as _

from wallet.models.base import BaseModel
from wallet.constants import CARD_TYPES, CARD_TYPE_VISA


class Card(BaseModel):
    """
    Card model for storing payment card information
    """
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='cards',
        verbose_name=_('Wallet')
    )
    card_type = models.CharField(
        max_length=20,
        choices=CARD_TYPES,
        default=CARD_TYPE_VISA,
        verbose_name=_('Card type')
    )
    last_four = models.CharField(
        max_length=4,
        verbose_name=_('Last four digits')
    )
    expiry_month = models.CharField(
        max_length=2,
        verbose_name=_('Expiry month')
    )
    expiry_year = models.CharField(
        max_length=4,
        verbose_name=_('Expiry year')
    )
    bin = models.CharField(
        max_length=6,
        blank=True,
        null=True,
        verbose_name=_('Bank Identification Number (BIN)')
    )
    card_holder_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('Card holder name')
    )
    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_('Email')
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_('Is default')
    )
    paystack_authorization_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Paystack authorization code')
    )
    paystack_authorization_signature = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('Paystack authorization signature')
    )
    paystack_card_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack card data')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    
    class Meta:
        verbose_name = _('Card')
        verbose_name_plural = _('Cards')
        ordering = ['-is_default', '-created_at']
        unique_together = ('wallet', 'paystack_authorization_code')
        indexes = [
            models.Index(fields=['wallet', 'is_default']),
            models.Index(fields=['paystack_authorization_code']),
        ]
    
    def __str__(self):
        return f"{self.get_card_type_display()} **** **** **** {self.last_four}"
    
    def save(self, *args, **kwargs):
        # If this card is being set as default, unset any other default cards for this wallet
        if self.is_default:
            Card.objects.filter(wallet=self.wallet, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
    
    def set_as_default(self):
        """Set this card as the default card for the wallet"""
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])
    
    def remove(self):
        """Mark the card as inactive instead of deleting it"""
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
        
        # Set another card as default if this was the default
        if not self.is_active and self.wallet.cards.filter(is_active=True).exists():
            new_default = self.wallet.cards.filter(is_active=True).first()
            new_default.set_as_default()
            
    @property
    def is_expired(self):
        """Check if the card is expired"""
        from datetime import datetime
        now = datetime.now()
        return (int(self.expiry_year) < now.year or 
                (int(self.expiry_year) == now.year and int(self.expiry_month) < now.month))
    
    @property
    def masked_pan(self):
        """Return masked PAN (e.g., '4123 **** **** 4567')"""
        return f"{self.bin or ''}{'*' * 6}{self.last_four}"