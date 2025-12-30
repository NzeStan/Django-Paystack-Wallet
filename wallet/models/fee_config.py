"""
Fee Configuration Models

Database-driven fee configurations for advanced customization.
Allows per-wallet, per-user, or global fee structures.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField

from wallet.models.base import BaseModel
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPES,
    FEE_BEARERS,
    FEE_TYPES,
    FEE_TYPE_HYBRID,
    FEE_BEARER_PLATFORM,
    PAYMENT_CHANNELS,
)


class FeeConfigurationManager(models.Manager):
    """Custom manager for FeeConfiguration"""
    
    def active(self):
        """Get only active configurations"""
        return self.filter(is_active=True)
    
    def for_wallet(self, wallet):
        """Get configurations for a specific wallet"""
        return self.filter(
            models.Q(wallet=wallet) | models.Q(wallet__isnull=True),
            is_active=True
        ).order_by('-wallet', '-priority')
    
    def for_transaction(self, wallet, transaction_type, payment_channel=None):
        """
        Get best matching configuration for a transaction
        
        Priority:
        1. Wallet-specific + transaction type + payment channel
        2. Wallet-specific + transaction type
        3. Global + transaction type + payment channel
        4. Global + transaction type
        """
        filters = models.Q(transaction_type=transaction_type, is_active=True)
        
        # Build query with priority
        query = self.filter(filters)
        
        # Wallet-specific with payment channel
        result = query.filter(
            wallet=wallet,
            payment_channel=payment_channel
        ).first()
        if result:
            return result
        
        # Wallet-specific without payment channel
        result = query.filter(
            wallet=wallet,
            payment_channel__isnull=True
        ).first()
        if result:
            return result
        
        # Global with payment channel
        result = query.filter(
            wallet__isnull=True,
            payment_channel=payment_channel
        ).first()
        if result:
            return result
        
        # Global without payment channel
        result = query.filter(
            wallet__isnull=True,
            payment_channel__isnull=True
        ).first()
        if result:
            return result
        
        return None


class FeeConfiguration(BaseModel):
    """
    Custom fee configuration model
    
    Allows defining custom fee structures for:
    - Specific wallets/users
    - Transaction types
    - Payment channels
    - With custom bearer rules
    
    Can override global settings for fine-grained control.
    """
    
    # ==========================================
    # SCOPE FIELDS
    # ==========================================
    
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='fee_configurations',
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_('Wallet'),
        help_text=_('Leave blank for global configuration')
    )
    
    name = models.CharField(
        max_length=200,
        verbose_name=_('Configuration Name'),
        help_text=_('Descriptive name for this fee configuration')
    )
    
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Description')
    )
    
    # ==========================================
    # TRANSACTION SCOPE
    # ==========================================
    
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        db_index=True,
        verbose_name=_('Transaction Type')
    )
    
    payment_channel = models.CharField(
        max_length=20,
        choices=PAYMENT_CHANNELS,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Payment Channel'),
        help_text=_('Optional: Specific payment channel for this config')
    )
    
    # ==========================================
    # FEE STRUCTURE
    # ==========================================
    
    fee_type = models.CharField(
        max_length=20,
        choices=FEE_TYPES,
        default=FEE_TYPE_HYBRID,
        verbose_name=_('Fee Type')
    )
    
    percentage_fee = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name=_('Percentage Fee'),
        help_text=_('Fee percentage (e.g., 1.5 for 1.5%)')
    )
    
    flat_fee = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Flat Fee'),
        help_text=_('Fixed fee amount')
    )
    
    fee_cap = MoneyField(
        max_digits=19,
        decimal_places=2,
        null=True,
        blank=True,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Fee Cap'),
        help_text=_('Maximum fee amount (optional)')
    )
    
    minimum_fee = MoneyField(
        max_digits=19,
        decimal_places=2,
        null=True,
        blank=True,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Minimum Fee'),
        help_text=_('Minimum fee amount (optional)')
    )
    
    # ==========================================
    # FEE WAIVER
    # ==========================================
    
    waiver_threshold = MoneyField(
        max_digits=19,
        decimal_places=2,
        null=True,
        blank=True,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Waiver Threshold'),
        help_text=_('Waive flat fee for transactions below this amount')
    )
    
    # ==========================================
    # BEARER CONFIGURATION
    # ==========================================
    
    fee_bearer = models.CharField(
        max_length=20,
        choices=FEE_BEARERS,
        default=FEE_BEARER_PLATFORM,
        verbose_name=_('Fee Bearer'),
        help_text=_('Who bears the transaction fee')
    )
    
    # For split bearer
    customer_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50,
        verbose_name=_('Customer Percentage'),
        help_text=_('Percentage of fee borne by customer (for split bearer)')
    )
    
    merchant_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50,
        verbose_name=_('Merchant Percentage'),
        help_text=_('Percentage of fee borne by merchant (for split bearer)')
    )
    
    # ==========================================
    # CONFIGURATION METADATA
    # ==========================================
    
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_('Is Active')
    )
    
    priority = models.IntegerField(
        default=0,
        verbose_name=_('Priority'),
        help_text=_('Higher priority configs are applied first')
    )
    
    valid_from = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Valid From'),
        help_text=_('Start date for this configuration')
    )
    
    valid_until = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Valid Until'),
        help_text=_('End date for this configuration')
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('Metadata'),
        help_text=_('Additional configuration data')
    )
    
    # Custom Manager
    objects = FeeConfigurationManager()
    
    class Meta:
        verbose_name = _('Fee Configuration')
        verbose_name_plural = _('Fee Configurations')
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['wallet', 'transaction_type'], name='fee_wallet_txn_idx'),
            models.Index(fields=['transaction_type', 'payment_channel'], name='fee_txn_channel_idx'),
            models.Index(fields=['is_active', 'priority'], name='fee_active_priority_idx'),
        ]
    
    def __str__(self):
        scope = f"{self.wallet.id}" if self.wallet else "Global"
        return f"{self.name} ({scope} - {self.get_transaction_type_display()})"
    
    def clean(self):
        """Validate the configuration"""
        from django.core.exceptions import ValidationError
        
        # Validate split percentages
        if self.fee_bearer == 'split':
            total = self.customer_percentage + self.merchant_percentage
            if total != 100:
                raise ValidationError({
                    'customer_percentage': _('Customer and merchant percentages must sum to 100')
                })
        
        # Validate fee type matches provided fields
        if self.fee_type == 'percentage' and self.percentage_fee == 0:
            raise ValidationError({
                'percentage_fee': _('Percentage fee must be greater than 0 for percentage fee type')
            })
        
        if self.fee_type == 'flat' and self.flat_fee.amount == 0:
            raise ValidationError({
                'flat_fee': _('Flat fee must be greater than 0 for flat fee type')
            })
    
    def calculate_fee(self, amount):
        """
        Calculate fee based on this configuration
        
        Args:
            amount: Money object
            
        Returns:
            Money object with calculated fee
        """
        from decimal import Decimal
        from djmoney.money import Money
        
        amount_value = amount.amount
        currency = amount.currency
        
        # Calculate base fee
        if self.fee_type == 'percentage':
            fee = amount_value * (Decimal(self.percentage_fee) / 100)
        elif self.fee_type == 'flat':
            fee = self.flat_fee.amount
        else:  # hybrid
            percentage_fee = amount_value * (Decimal(self.percentage_fee) / 100)
            
            # Check waiver threshold
            if self.waiver_threshold and amount_value < self.waiver_threshold.amount:
                fee = percentage_fee  # Skip flat fee
            else:
                fee = percentage_fee + self.flat_fee.amount
        
        # Apply minimum fee
        if self.minimum_fee and fee < self.minimum_fee.amount:
            fee = self.minimum_fee.amount
        
        # Apply fee cap
        if self.fee_cap and fee > self.fee_cap.amount:
            fee = self.fee_cap.amount
        
        return Money(fee, currency)


class FeeTier(BaseModel):
    """
    Fee tier for amount-based fee structures
    
    Allows defining different fees based on transaction amount ranges.
    Example: Transfers under 5000 = NGN 10, 5000-50000 = NGN 25, etc.
    """
    
    configuration = models.ForeignKey(
        FeeConfiguration,
        on_delete=models.CASCADE,
        related_name='tiers',
        verbose_name=_('Fee Configuration')
    )
    
    min_amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Minimum Amount'),
        help_text=_('Minimum transaction amount for this tier (inclusive)')
    )
    
    max_amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        null=True,
        blank=True,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Maximum Amount'),
        help_text=_('Maximum transaction amount for this tier (inclusive, null = unlimited)')
    )
    
    fee_amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default=0,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Fee Amount'),
        help_text=_('Fixed fee for this tier')
    )
    
    class Meta:
        verbose_name = _('Fee Tier')
        verbose_name_plural = _('Fee Tiers')
        ordering = ['min_amount']
        indexes = [
            models.Index(fields=['configuration', 'min_amount'], name='tier_config_min_idx'),
        ]
    
    def __str__(self):
        max_display = f"{self.max_amount.amount}" if self.max_amount else "unlimited"
        return f"{self.min_amount.amount} - {max_display}: {self.fee_amount.amount}"
    
    def applies_to(self, amount):
        """Check if this tier applies to the given amount"""
        if amount.amount < self.min_amount.amount:
            return False
        
        if self.max_amount and amount.amount > self.max_amount.amount:
            return False
        
        return True


class FeeHistory(BaseModel):
    """
    Fee calculation history/audit trail
    
    Stores historical fee calculations for analytics and debugging.
    """
    
    transaction = models.OneToOneField(
        'wallet.Transaction',
        on_delete=models.CASCADE,
        related_name='fee_history',
        verbose_name=_('Transaction')
    )
    
    configuration_used = models.ForeignKey(
        FeeConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fee_histories',
        verbose_name=_('Configuration Used'),
        help_text=_('Fee configuration that was used for calculation')
    )
    
    calculation_method = models.CharField(
        max_length=50,
        verbose_name=_('Calculation Method'),
        help_text=_('settings, database, custom, etc.')
    )
    
    original_amount = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Original Amount')
    )
    
    calculated_fee = MoneyField(
        max_digits=19,
        decimal_places=2,
        default_currency=get_wallet_setting('CURRENCY'),
        verbose_name=_('Calculated Fee')
    )
    
    fee_bearer = models.CharField(
        max_length=20,
        choices=FEE_BEARERS,
        verbose_name=_('Fee Bearer')
    )
    
    calculation_details = models.JSONField(
        default=dict,
        verbose_name=_('Calculation Details'),
        help_text=_('Detailed breakdown of fee calculation')
    )
    
    class Meta:
        verbose_name = _('Fee History')
        verbose_name_plural = _('Fee Histories')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction'], name='fee_history_txn_idx'),
            models.Index(fields=['created_at'], name='fee_history_created_idx'),
        ]
    
    def __str__(self):
        return f"Fee history for transaction {self.transaction.reference}"