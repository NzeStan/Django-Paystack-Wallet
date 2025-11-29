from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Avg
from decimal import Decimal

from wallet.models import Card
from wallet.constants import CARD_TYPES, TRANSACTION_STATUS_SUCCESS


# ==========================================
# CARD SERIALIZERS
# ==========================================

class CardSerializer(serializers.ModelSerializer):
    """
    Standard serializer for the Card model
    
    Provides basic card information with security considerations.
    Never exposes full card numbers or sensitive data.
    
    SECURITY: Card holder name and email are read-only as they're
    automatically filled from wallet.user details.
    """
    
    # Related fields
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
    
    # Display fields
    card_type_display = serializers.CharField(
        source='get_card_type_display',
        read_only=True
    )
    is_expired = serializers.BooleanField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    masked_pan = serializers.CharField(read_only=True)
    expiry = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    
    class Meta:
        model = Card
        fields = [
            'id',
            'wallet_id',
            'card_type',
            'card_type_display',
            'last_four',
            'expiry_month',
            'expiry_year',
            'expiry',
            'bin',
            'card_holder_name',
            'email',
            'is_default',
            'is_active',
            'is_expired',
            'is_valid',
            'masked_pan',
            'display_name',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'wallet_id',
            'card_type',
            'card_type_display',
            'last_four',
            'expiry_month',
            'expiry_year',
            'expiry',
            'bin',
            'card_holder_name',  
            'email',  
            'is_default',  
            'is_active', 
            'is_expired',
            'is_valid',
            'masked_pan',
            'display_name',
            'created_at',
            'updated_at'
        ]


class CardListSerializer(CardSerializer):
    """
    Optimized serializer for listing cards
    
    Includes minimal information for efficient list views.
    """
    
    class Meta(CardSerializer.Meta):
        fields = [
            'id',
            'card_type_display',
            'masked_pan',
            'expiry',
            'is_default',
            'is_active',
            'is_expired',
            'display_name'
        ]
        read_only_fields = fields


class CardDetailSerializer(CardSerializer):
    """
    Detailed serializer for the Card model
    
    Includes comprehensive information with transaction statistics.
    
    FIXED: Properly handles Decimal from aggregate functions
    """
    
    # Statistics
    transaction_count = serializers.SerializerMethodField(read_only=True)
    total_amount = serializers.SerializerMethodField(read_only=True)
    successful_transactions = serializers.SerializerMethodField(read_only=True)
    average_transaction_amount = serializers.SerializerMethodField(read_only=True)
    last_used = serializers.SerializerMethodField(read_only=True)
    
    class Meta(CardSerializer.Meta):
        fields = CardSerializer.Meta.fields + [
            'paystack_authorization_code',
            'transaction_count',
            'total_amount',
            'successful_transactions',
            'average_transaction_amount',
            'last_used'
        ]
        read_only_fields = CardSerializer.Meta.read_only_fields + [
            'paystack_authorization_code',
            'transaction_count',
            'total_amount',
            'successful_transactions',
            'average_transaction_amount',
            'last_used'
        ]
    
    def get_transaction_count(self, card):
        """Get the count of transactions made with this card"""
        return card.transactions.count()
    
    def get_total_amount(self, card):
        """
        Get the total amount of successful transactions
        
        FIXED: Sum() returns Decimal, not Money object
        """
        result = card.transactions.filter(
            status=TRANSACTION_STATUS_SUCCESS
        ).aggregate(total=Sum('amount'))
        
        total = result.get('total')
        if total is not None:
            # Aggregate returns Decimal directly, not Money
            # Get currency from card's wallet
            try:
                currency = card.wallet.balance.currency.code
            except (AttributeError, TypeError):
                currency = 'NGN'  # Default fallback
            
            return {
                'amount': float(total),  # Direct conversion from Decimal
                'currency': currency
            }
        return None
    
    def get_successful_transactions(self, card):
        """Get the count of successful transactions"""
        return card.transactions.filter(
            status=TRANSACTION_STATUS_SUCCESS
        ).count()
    
    def get_average_transaction_amount(self, card):
        """
        Get the average amount of successful transactions
        
        FIXED: Avg() returns Decimal, not Money object
        """
        result = card.transactions.filter(
            status=TRANSACTION_STATUS_SUCCESS
        ).aggregate(avg=Avg('amount'))
        
        avg = result.get('avg')
        if avg is not None:
            # Aggregate returns Decimal directly, not Money
            # Get currency from card's wallet
            try:
                currency = card.wallet.balance.currency.code
            except (AttributeError, TypeError):
                currency = 'NGN'  # Default fallback
            
            return {
                'amount': float(avg),  # Direct conversion from Decimal
                'currency': currency
            }
        return None
    
    def get_last_used(self, card):
        """Get the date of the last transaction"""
        last_transaction = card.transactions.order_by('-created_at').first()
        if last_transaction:
            return last_transaction.created_at
        return None


class CardUpdateSerializer(serializers.ModelSerializer):
    """
    RESTRICTED serializer for card updates
    
    This serializer is NOT used in the API.
    PUT/PATCH endpoints are disabled (not in http_method_names).
    
    Users should use specific actions like set_default, activate, deactivate
    instead of generic update operations.
    
    Kept for potential internal use but not exposed through API.
    """
    
    class Meta:
        model = Card
        fields = []  # No fields allowed for update
        read_only_fields = [
            'card_holder_name',
            'email',
            'is_default',
            'is_active'
        ]


class CardChargeSerializer(serializers.Serializer):
    """
    Serializer for charging a saved card
    
    Validates payment amount and optional metadata for card charges.
    Amount is automatically converted to kobo when sent to Paystack.
    """
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01"),
        help_text=_('Amount to charge in Naira (automatically converted to kobo for Paystack)')
    )
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default='Card charge',
        help_text=_('Transaction description')
    )
    reference = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text=_('Custom transaction reference (auto-generated if not provided)')
    )
    metadata = serializers.JSONField(
        required=False,
        default=dict,
        help_text=_('Additional metadata for the transaction')
    )
    
    def validate_amount(self, value):
        """
        Validate amount
        
        Args:
            value (Decimal): Amount
            
        Returns:
            Decimal: Validated amount
        """
        if value <= 0:
            raise serializers.ValidationError(
                _("Amount must be greater than zero")
            )
        
        # Check for reasonable maximum (e.g., 10 million Naira)
        if value > Decimal("10000000"):
            raise serializers.ValidationError(
                _("Amount exceeds maximum allowed value of ₦10,000,000")
            )
        
        return value
    
    def validate_metadata(self, value):
        """
        Validate metadata
        
        Args:
            value (dict): Metadata
            
        Returns:
            dict: Validated metadata
        """
        if not value:
            return {}
        
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                _("Metadata must be a valid JSON object")
            )
        
        return value


class CardInitializeSerializer(serializers.Serializer):
    """
    Serializer for initializing a card payment
    
    Used to start the card payment flow with Paystack.
    
    SECURITY:
    - Email is NOT required - it's automatically filled from wallet.user.email
    - Card holder name is NOT required - it's automatically filled from wallet.user.get_full_name()
    - Amount is automatically converted to kobo for Paystack
    """
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01"),
        help_text=_('Amount to charge in Naira (automatically converted to kobo for Paystack)')
    )
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default='Card deposit to wallet',
        help_text=_('Transaction description')
    )
    reference = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text=_('Custom transaction reference (auto-generated if not provided)')
    )
    callback_url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text=_('URL to redirect after payment')
    )
    metadata = serializers.JSONField(
        required=False,
        default=dict,
        help_text=_('Additional metadata for the transaction')
    )
    
    def validate_amount(self, value):
        """
        Validate amount
        
        Args:
            value (Decimal): Amount
            
        Returns:
            Decimal: Validated amount
        """
        if value <= 0:
            raise serializers.ValidationError(
                _("Amount must be greater than zero")
            )
        
        # Check for reasonable maximum (e.g., 10 million Naira)
        if value > Decimal("10000000"):
            raise serializers.ValidationError(
                _("Amount exceeds maximum allowed value of ₦10,000,000")
            )
        
        return value
    
    def validate_metadata(self, value):
        """
        Validate metadata
        
        Args:
            value (dict): Metadata
            
        Returns:
            dict: Validated metadata
        """
        if not value:
            return {}
        
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                _("Metadata must be a valid JSON object")
            )
        
        return value


class CardSetDefaultSerializer(serializers.Serializer):
    """
    Serializer for setting a card as default
    
    Simple serializer for the set_default action.
    No fields required - the action works on the card specified in the URL.
    """
    
    pass  # No additional fields needed


class CardStatisticsSerializer(serializers.Serializer):
    """
    Serializer for card statistics
    
    Provides comprehensive statistics for a card.
    Card IS directly linked to Transaction, so statistics come from card.transactions
    """
    
    # Card info
    id = serializers.UUIDField(read_only=True)
    card_type = serializers.CharField(read_only=True)
    last_four = serializers.CharField(read_only=True)
    masked_pan = serializers.CharField(read_only=True)
    
    # Statistics from card.transactions
    total_transactions = serializers.IntegerField(read_only=True)
    successful_transactions = serializers.IntegerField(read_only=True)
    failed_transactions = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=2,
        read_only=True
    )
    average_amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=2,
        read_only=True
    )
    
    # Status
    is_default = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    
    # Dates
    last_used = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)