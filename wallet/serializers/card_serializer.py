from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from wallet.models import Card


class CardSerializer(serializers.ModelSerializer):
    """Serializer for the Card model"""
    
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
    card_type_display = serializers.CharField(source='get_card_type_display', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    masked_pan = serializers.CharField(read_only=True)
    
    class Meta:
        model = Card
        fields = [
            'id', 'wallet_id', 'card_type', 'card_type_display', 'last_four',
            'expiry_month', 'expiry_year', 'bin', 'card_holder_name', 'email',
            'is_default', 'is_active', 'is_expired', 'masked_pan',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'wallet_id', 'card_type', 'card_type_display', 'last_four',
            'expiry_month', 'expiry_year', 'bin', 'is_expired', 'masked_pan',
            'created_at', 'updated_at'
        ]


class CardDetailSerializer(CardSerializer):
    """Detailed serializer for the Card model"""
    
    transaction_count = serializers.SerializerMethodField(read_only=True)
    
    class Meta(CardSerializer.Meta):
        fields = CardSerializer.Meta.fields + ['transaction_count']
        read_only_fields = CardSerializer.Meta.read_only_fields + ['transaction_count']
    
    def get_transaction_count(self, card):
        """Get the count of transactions made with this card"""
        return card.transactions.count()


class CardUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating card information"""
    
    class Meta:
        model = Card
        fields = ['card_holder_name', 'email', 'is_default', 'is_active']


class CardChargeSerializer(serializers.Serializer):
    """Serializer for charging a card"""
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01")
    )
    description = serializers.CharField(required=False)
    reference = serializers.CharField(required=False)
    metadata = serializers.JSONField(required=False)
    
    def validate_amount(self, value):
        """Validate amount is positive"""
        if value <= 0:
            raise serializers.ValidationError(_("Amount must be greater than zero"))
        return value


class CardInitializeSerializer(serializers.Serializer):
    """Serializer for initializing a card payment"""
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal(0.01)
    )
    email = serializers.EmailField(required=False)
    callback_url = serializers.URLField(required=False)
    reference = serializers.CharField(required=False)
    metadata = serializers.JSONField(required=False)
    
    def validate_amount(self, value):
        """Validate amount is positive"""
        if value <= 0:
            raise serializers.ValidationError(_("Amount must be greater than zero"))
        return value