from rest_framework import serializers

from wallet.constants import BANK_ACCOUNT_TYPES
from wallet.models import Bank, BankAccount


class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = ['id', 'name', 'code', 'slug', 'country', 'currency', 'type', 'pay_with_bank', 'is_active']
        read_only_fields = fields


class BankAccountSerializer(serializers.ModelSerializer):
    bank = BankSerializer(read_only=True)
    masked_account_number = serializers.CharField(read_only=True)
    can_receive_transfers = serializers.BooleanField(read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            'id', 'bank', 'account_number', 'masked_account_number', 'account_name', 'account_type',
            'recipient_type', 'currency', 'is_verified', 'is_default', 'is_active', 'can_receive_transfers',
            'created_at',
        ]
        read_only_fields = fields


BankAccountDetailSerializer = BankAccountSerializer


class BankAccountCreateSerializer(serializers.Serializer):
    bank_code = serializers.CharField(max_length=20)
    account_number = serializers.CharField(max_length=20)
    account_type = serializers.ChoiceField(choices=BANK_ACCOUNT_TYPES, required=False)
    currency = serializers.CharField(max_length=3, required=False)
    set_default = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate_account_number(self, value):
        value = value.strip()
        if not value.isdigit():
            raise serializers.ValidationError("Account number must contain only digits")
        return value


class ResolveAccountSerializer(serializers.Serializer):
    bank_code = serializers.CharField(max_length=20)
    account_number = serializers.CharField(max_length=20)
