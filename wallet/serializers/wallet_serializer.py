from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
import datetime
from wallet.models import Wallet
from decimal import Decimal

class WalletSerializer(serializers.ModelSerializer):
    """Serializer for the Wallet model"""
    
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField(read_only=True)
    balance_amount = serializers.DecimalField(
        source='balance.amount', 
        decimal_places=2, 
        max_digits=19, 
        read_only=True
    )
    balance_currency = serializers.CharField(source='balance.currency.code', read_only=True)
    daily_transaction_total_amount = serializers.DecimalField(
        source='daily_transaction_total.amount', 
        decimal_places=2, 
        max_digits=19, 
        read_only=True
    )
    daily_transaction_reset = serializers.SerializerMethodField()
    class Meta:
        model = Wallet
        fields = [
            'id', 'user', 'user_email', 'user_name', 'balance_amount', 'balance_currency',
            'tag', 'is_active', 'is_locked', 'last_transaction_date', 
            'daily_transaction_total_amount', 'daily_transaction_count',
            'daily_transaction_reset', 'created_at', 'updated_at',
            'dedicated_account_number', 'dedicated_account_bank'
        ]
        read_only_fields = [
            'id', 'user', 'balance_amount', 'balance_currency', 'last_transaction_date',
            'daily_transaction_total_amount', 'daily_transaction_count',
            'daily_transaction_reset', 'created_at', 'updated_at',
            'dedicated_account_number', 'dedicated_account_bank'
        ]
    
    def get_user_name(self, wallet):
        """Get user's name if available"""
        user = wallet.user
        # Try to get the user's full name, if available
        if hasattr(user, 'get_full_name'):
            return user.get_full_name()
        # Fall back to the user's name attribute, if available
        elif hasattr(user, 'name'):
            return user.name
        # Use the username as a last resort
        elif hasattr(user, 'username'):
            return user.username
        # If all else fails, return None
        return None
    
    def get_daily_transaction_reset(self, wallet):
        if wallet.daily_transaction_reset:
            if isinstance(wallet.daily_transaction_reset, datetime.datetime):
                return wallet.daily_transaction_reset.date()
            return wallet.daily_transaction_reset
        return None

class WalletDetailSerializer(WalletSerializer):
    """Detailed serializer for the Wallet model including additional information"""
    
    transaction_count = serializers.SerializerMethodField(read_only=True)
    cards_count = serializers.SerializerMethodField(read_only=True)
    bank_accounts_count = serializers.SerializerMethodField(read_only=True)
    
    class Meta(WalletSerializer.Meta):
        fields = WalletSerializer.Meta.fields + [
            'transaction_count', 'cards_count', 'bank_accounts_count',
            'paystack_customer_code'
        ]
        read_only_fields = WalletSerializer.Meta.read_only_fields + [
            'transaction_count', 'cards_count', 'bank_accounts_count',
            'paystack_customer_code'
        ]
    
    def get_transaction_count(self, wallet):
        """Get total transaction count"""
        return wallet.transactions.count()
    
    def get_cards_count(self, wallet):
        """Get active cards count"""
        return wallet.cards.filter(is_active=True).count()
    
    def get_bank_accounts_count(self, wallet):
        """Get active bank accounts count"""
        return wallet.bank_accounts.filter(is_active=True).count()


class WalletCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating wallets"""
    
    class Meta:
        model = Wallet
        fields = ['tag', 'is_active', 'is_locked']


class WalletTransactionSerializer(serializers.Serializer):
    """Serializer for wallet transaction operations"""
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01")
    )
    description = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)
    
    def validate_amount(self, value):
        """Validate amount is positive"""
        if value <= 0:
            raise serializers.ValidationError(_(f"Invalid amount: {value}. Amount must be greater than zero."))
        return value


class WalletDepositSerializer(WalletTransactionSerializer):
    """Serializer for wallet deposit operations"""
    
    callback_url = serializers.URLField(required=False)
    email = serializers.EmailField(required=False)
    
    
class WalletWithdrawSerializer(WalletTransactionSerializer):
    """Serializer for wallet withdrawal operations"""
    
    bank_account_id = serializers.CharField(required=True)
    
class WalletTransferSerializer(WalletTransactionSerializer):
    """Serializer for wallet transfer operations"""
    
    destination_wallet_id = serializers.CharField()
    
    def validate(self, data):
        """Validate transfer data"""
        # Destination wallet is required
        if 'destination_wallet_id' not in data:
            raise serializers.ValidationError({
                'destination_wallet_id': _("Destination wallet ID is required")
            })
        return data
    
class FinalizeWithdrawalSerializer(serializers.Serializer):
    transfer_code = serializers.CharField(max_length=100)
    otp = serializers.CharField(max_length=10)
    
    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must contain only digits")
        if len(value) < 4 or len(value) > 10:
            raise serializers.ValidationError("OTP must be between 4 and 10 digits")
        return value