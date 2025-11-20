"""
Django Paystack Wallet - Card Serializers
Comprehensive serializers with validation and optimization
"""
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Sum, Avg, Q
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
        """Get the total amount of successful transactions"""
        result = card.transactions.filter(
            status=TRANSACTION_STATUS_SUCCESS
        ).aggregate(total=Sum('amount'))
        
        total = result.get('total')
        if total:
            return {
                'amount': float(total.amount),
                'currency': str(total.currency)
            }
        return None
    
    def get_successful_transactions(self, card):
        """Get the count of successful transactions"""
        return card.transactions.filter(
            status=TRANSACTION_STATUS_SUCCESS
        ).count()
    
    def get_average_transaction_amount(self, card):
        """Get the average amount of successful transactions"""
        result = card.transactions.filter(
            status=TRANSACTION_STATUS_SUCCESS
        ).aggregate(avg=Avg('amount'))
        
        avg = result.get('avg')
        if avg:
            return {
                'amount': float(avg.amount),
                'currency': str(avg.currency)
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
    Serializer for updating card information
    
    Allows updating specific fields while protecting sensitive data.
    """
    
    class Meta:
        model = Card
        fields = [
            'card_holder_name',
            'email',
            'is_default',
            'is_active'
        ]
        extra_kwargs = {
            'card_holder_name': {
                'help_text': _('Update cardholder name')
            },
            'email': {
                'help_text': _('Update email associated with card')
            }
        }
    
    def validate_is_default(self, value):
        """
        Validate is_default field
        
        Args:
            value (bool): Is default value
            
        Returns:
            bool: Validated value
        """
        # If setting to False, ensure there's another default card
        if not value and self.instance.is_default:
            wallet = self.instance.wallet
            other_defaults = Card.objects.filter(
                wallet=wallet,
                is_default=True,
                is_active=True
            ).exclude(pk=self.instance.pk).count()
            
            if other_defaults == 0:
                raise serializers.ValidationError(
                    _("Cannot unset default. Please set another card as default first.")
                )
        
        return value
    
    def validate_is_active(self, value):
        """
        Validate is_active field
        
        Args:
            value (bool): Is active value
            
        Returns:
            bool: Validated value
        """
        # Check if card is expired before activating
        if value and self.instance.is_expired:
            raise serializers.ValidationError(
                _("Cannot activate an expired card")
            )
        
        return value


class CardChargeSerializer(serializers.Serializer):
    """
    Serializer for charging a saved card
    
    Validates payment amount and optional metadata for card charges.
    """
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01"),
        help_text=_('Amount to charge in the wallet currency')
    )
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
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
        
        # Check for reasonable maximum (e.g., 10 million)
        if value > Decimal("10000000"):
            raise serializers.ValidationError(
                _("Amount exceeds maximum allowed value")
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
    """
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01"),
        help_text=_('Amount to charge')
    )
    email = serializers.EmailField(
        required=False,
        help_text=_('Customer email (defaults to wallet user email)')
    )
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text=_('Transaction description')
    )
    reference = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text=_('Custom transaction reference')
    )
    callback_url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text=_('URL to redirect after payment')
    )
    metadata = serializers.JSONField(
        required=False,
        help_text=_('Additional metadata')
    )
    
    def validate_amount(self, value):
        """Validate amount"""
        if value <= 0:
            raise serializers.ValidationError(
                _("Amount must be greater than zero")
            )
        
        if value > Decimal("10000000"):
            raise serializers.ValidationError(
                _("Amount exceeds maximum allowed value")
            )
        
        return value


class CardSetDefaultSerializer(serializers.Serializer):
    """
    Serializer for setting a card as default
    
    Simple serializer for the set_default action.
    """
    
    pass  # No additional fields needed


class CardStatisticsSerializer(serializers.Serializer):
    """
    Serializer for card statistics
    
    Provides comprehensive statistics for a card.
    """
    
    # Card info
    id = serializers.UUIDField(read_only=True)
    card_type = serializers.CharField(read_only=True)
    last_four = serializers.CharField(read_only=True)
    masked_pan = serializers.CharField(read_only=True)
    
    # Statistics
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