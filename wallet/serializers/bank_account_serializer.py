from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from wallet.models import BankAccount, Bank


class BankSerializer(serializers.ModelSerializer):
    """Serializer for the Bank model"""
    
    class Meta:
        model = Bank
        fields = [
            'id', 'name', 'code', 'slug', 'country',
            'currency', 'type', 'is_active'
        ]
        read_only_fields = fields


class BankAccountSerializer(serializers.ModelSerializer):
    """Serializer for the BankAccount model"""
    
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
    bank_name = serializers.CharField(source='bank.name', read_only=True)
    bank_code = serializers.CharField(source='bank.code', read_only=True)
    account_type_display = serializers.CharField(source='get_account_type_display', read_only=True)
    
    class Meta:
        model = BankAccount
        fields = [
            'id', 'wallet_id', 'bank_name', 'bank_code', 'account_number',
            'account_name', 'account_type', 'account_type_display', 
            'is_verified', 'is_default', 'is_active', 'bvn',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'wallet_id', 'bank_name', 'is_verified',
            'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'bvn': {'write_only': True}
        }


class BankAccountDetailSerializer(BankAccountSerializer):
    """Detailed serializer for the BankAccount model"""
    
    transaction_count = serializers.SerializerMethodField(read_only=True)
    settlement_count = serializers.SerializerMethodField(read_only=True)
    bank_details = BankSerializer(source='bank', read_only=True)
    
    class Meta(BankAccountSerializer.Meta):
        fields = BankAccountSerializer.Meta.fields + [
            'transaction_count', 'settlement_count', 'bank_details'
        ]
        read_only_fields = BankAccountSerializer.Meta.read_only_fields + [
            'transaction_count', 'settlement_count', 'bank_details'
        ]
    
    def get_transaction_count(self, bank_account):
        """Get the count of transactions for this bank account"""
        return bank_account.transactions.count()
    
    def get_settlement_count(self, bank_account):
        """Get the count of settlements for this bank account"""
        return bank_account.settlements.count()


class BankAccountCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a bank account"""
    
    bank_code = serializers.CharField(write_only=True)
    
    class Meta:
        model = BankAccount
        fields = [
            'bank_code', 'account_number', 'account_name',
            'account_type', 'bvn', 'is_default'
        ]
        extra_kwargs = {
            'account_name': {'required': False},
            'bvn': {'required': False, 'write_only': True}
        }
    
    def validate_bank_code(self, value):
        """Validate bank code exists"""
        try:
            Bank.objects.get(code=value)
        except Bank.DoesNotExist:
            raise serializers.ValidationError(_("Invalid bank code"))
        return value
    
    def validate_account_number(self, value):
        """Validate account number format"""
        if not value.isdigit():
            raise serializers.ValidationError(_("Account number must contain only digits"))
        
        if len(value) < 10 or len(value) > 10:
            raise serializers.ValidationError(_("Account number must be 10 digits"))
        
        return value
    
    def validate_bvn(self, value):
        """Validate BVN format if provided"""
        if value and not value.isdigit():
            raise serializers.ValidationError(_("BVN must contain only digits"))
        
        if value and len(value) != 11:
            raise serializers.ValidationError(_("BVN must be 11 digits"))
        
        return value


class BankAccountUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a bank account"""
    
    class Meta:
        model = BankAccount
        fields = ['account_name', 'is_default', 'is_active']


class BankAccountVerifySerializer(serializers.Serializer):
    """Serializer for verifying a bank account"""
    
    account_number = serializers.CharField()
    bank_code = serializers.CharField()
    
    def validate_account_number(self, value):
        """Validate account number format"""
        if not value.isdigit():
            raise serializers.ValidationError(_("Account number must contain only digits"))
        
        if len(value) < 10 or len(value) > 10:
            raise serializers.ValidationError(_("Account number must be 10 digits"))
        
        return value
    
    def validate_bank_code(self, value):
        """Validate bank code exists"""
        try:
            Bank.objects.get(code=value)
        except Bank.DoesNotExist:
            raise serializers.ValidationError(_("Invalid bank code"))
        return value