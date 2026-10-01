from rest_framework import serializers

from wallet.models import Card


class CardSerializer(serializers.ModelSerializer):
    card_type_display = serializers.CharField(source='get_card_type_display', read_only=True)
    masked_pan = serializers.CharField(read_only=True)
    expiry = serializers.CharField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Card
        fields = [
            'id', 'card_type', 'card_type_display', 'last_four', 'masked_pan', 'expiry', 'expiry_month',
            'expiry_year', 'bank', 'country_code', 'card_holder_name', 'is_default', 'is_active', 'is_expired',
            'created_at',
        ]
        read_only_fields = fields


CardDetailSerializer = CardSerializer
