"""
Django Paystack Wallet - Bank Account Serializers
Comprehensive serializers with validation and optimization
"""
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Sum, Q

from wallet.models import BankAccount, Bank
from wallet.constants import BANK_ACCOUNT_TYPES, TRANSACTION_STATUS_SUCCESS, SETTLEMENT_STATUS_SUCCESS


# ==========================================
# BANK SERIALIZERS
# ==========================================

class BankSerializer(serializers.ModelSerializer):
    """
    Serializer for the Bank model
    
    Provides read-only access to bank information.
    """
    
    class Meta:
        model = Bank
        fields = [
            'id',
            'name',
            'code',
            'slug',
            'country',
            'currency',
            'type',
            'is_active',
            'created_at'
        ]
        read_only_fields = fields


class BankDetailSerializer(BankSerializer):
    """
    Detailed serializer for the Bank model
    
    Includes additional information and statistics.
    """
    
    account_count = serializers.SerializerMethodField(read_only=True)
    
    class Meta(BankSerializer.Meta):
        fields = BankSerializer.Meta.fields + ['account_count']
        read_only_fields = BankSerializer.Meta.fields + ['account_count']
    
    def get_account_count(self, bank):
        """Get the count of bank accounts for this bank"""
        return bank.bank_accounts.filter(is_active=True).count()


# ==========================================
# BANK ACCOUNT SERIALIZERS
# ==========================================

class BankAccountSerializer(serializers.ModelSerializer):
    """
    Standard serializer for the BankAccount model
    
    Provides basic bank account information with related data.
    """
    
    # Related fields
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
    bank_name = serializers.CharField(source='bank.name', read_only=True)
    bank_code = serializers.CharField(source='bank.code', read_only=True)
    
    # Display fields
    account_type_display = serializers.CharField(
        source='get_account_type_display',
        read_only=True
    )
    masked_account_number = serializers.CharField(read_only=True)
    full_bank_name = serializers.CharField(read_only=True)
    
    class Meta:
        model = BankAccount
        fields = [
            'id',
            'wallet_id',
            'bank_name',
            'bank_code',
            'account_number',
            'masked_account_number',
            'account_name',
            'account_type',
            'account_type_display',
            'full_bank_name',
            'is_verified',
            'is_default',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'wallet_id',
            'bank_name',
            'bank_code',
            'masked_account_number',
            'account_type_display',
            'full_bank_name',
            'is_verified',
            'created_at',
            'updated_at'
        ]


class BankAccountListSerializer(BankAccountSerializer):
    """
    Optimized serializer for listing bank accounts
    
    Includes minimal information for efficient list views.
    """
    
    class Meta(BankAccountSerializer.Meta):
        fields = [
            'id',
            'bank_name',
            'account_name',
            'masked_account_number',
            'account_type_display',
            'is_default',
            'is_active',
            'is_verified'
        ]
        read_only_fields = fields


class BankAccountDetailSerializer(BankAccountSerializer):
    """
    Detailed serializer for the BankAccount model
    
    Includes comprehensive information with statistics.
    """
    
    # Related details
    bank_details = BankSerializer(source='bank', read_only=True)
    
    # Statistics
    transaction_count = serializers.SerializerMethodField(read_only=True)
    settlement_count = serializers.SerializerMethodField(read_only=True)
    total_settled_amount = serializers.SerializerMethodField(read_only=True)
    successful_settlements = serializers.SerializerMethodField(read_only=True)
    
    class Meta(BankAccountSerializer.Meta):
        fields = BankAccountSerializer.Meta.fields + [
            'bank_details',
            'paystack_recipient_code',
            'transaction_count',
            'settlement_count',
            'total_settled_amount',
            'successful_settlements'
        ]
        read_only_fields = BankAccountSerializer.Meta.read_only_fields + [
            'bank_details',
            'paystack_recipient_code',
            'transaction_count',
            'settlement_count',
            'total_settled_amount',
            'successful_settlements'
        ]
    
    def get_transaction_count(self, bank_account):
        """Get the count of transactions for this bank account"""
        return bank_account.transactions.count()
    
    def get_settlement_count(self, bank_account):
        """Get the count of settlements for this bank account"""
        return bank_account.settlements.count()
    
    def get_total_settled_amount(self, bank_account):
        """Get the total amount settled through this bank account"""
        result = bank_account.settlements.filter(
            status=SETTLEMENT_STATUS_SUCCESS
        ).aggregate(total=Sum('amount'))
        
        total = result.get('total')
        if total:
            return {
                'amount': float(total.amount),
                'currency': str(total.currency)
            }
        return None
    
    def get_successful_settlements(self, bank_account):
        """Get the count of successful settlements"""
        return bank_account.settlements.filter(
            status=SETTLEMENT_STATUS_SUCCESS
        ).count()


class BankAccountCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a bank account
    
    Validates and processes new bank account creation with Paystack integration.
    """
    
    bank_code = serializers.CharField(
        write_only=True,
        help_text=_('Bank code from the banks list')
    )
    
    class Meta:
        model = BankAccount
        fields = [
            'bank_code',
            'account_number',
            'account_name',
            'account_type',
            'bvn',
            'is_default'
        ]
        extra_kwargs = {
            'account_name': {
                'required': False,
                'help_text': _('Account name (will be auto-fetched if not provided)')
            },
            'account_type': {
                'required': False,
                'help_text': _('Account type (savings or current)')
            },
            'bvn': {
                'required': False,
                'write_only': True,
                'help_text': _('Bank Verification Number (optional)')
            },
            'is_default': {
                'required': False,
                'help_text': _('Set as default account')
            }
        }
    
    def validate_bank_code(self, value):
        """
        Validate that the bank code exists
        
        Args:
            value (str): Bank code
            
        Returns:
            str: Validated bank code
            
        Raises:
            ValidationError: If bank code is invalid
        """
        try:
            Bank.objects.get(code=value, is_active=True)
        except Bank.DoesNotExist:
            raise serializers.ValidationError(
                _("Invalid or inactive bank code. Please select a valid bank.")
            )
        return value
    
    def validate_account_number(self, value):
        """
        Validate account number format
        
        Args:
            value (str): Account number
            
        Returns:
            str: Validated account number
            
        Raises:
            ValidationError: If account number is invalid
        """
        # Remove any spaces or hyphens
        value = value.replace(' ', '').replace('-', '')
        
        # Check if it's numeric
        if not value.isdigit():
            raise serializers.ValidationError(
                _("Account number must contain only digits")
            )
        
        # Check length (most banks use 10 digits)
        if len(value) < 10 or len(value) > 20:
            raise serializers.ValidationError(
                _("Account number must be between 10 and 20 digits")
            )
        
        return value
    
    def validate_bvn(self, value):
        """
        Validate BVN format
        
        Args:
            value (str): BVN
            
        Returns:
            str: Validated BVN
            
        Raises:
            ValidationError: If BVN is invalid
        """
        if not value:
            return value
        
        # Remove any spaces
        value = value.replace(' ', '')
        
        # Check if it's numeric
        if not value.isdigit():
            raise serializers.ValidationError(
                _("BVN must contain only digits")
            )
        
        # Check length (BVN is 11 digits)
        if len(value) != 11:
            raise serializers.ValidationError(
                _("BVN must be exactly 11 digits")
            )
        
        return value
    
    def validate(self, attrs):
        """
        Validate the entire data
        
        Args:
            attrs (dict): Validated data
            
        Returns:
            dict: Validated data
            
        Raises:
            ValidationError: If validation fails
        """
        # Check for duplicate account
        wallet = self.context.get('wallet')
        if wallet:
            bank = Bank.objects.get(code=attrs['bank_code'])
            existing = BankAccount.objects.filter(
                wallet=wallet,
                bank=bank,
                account_number=attrs['account_number']
            ).first()
            
            if existing:
                raise serializers.ValidationError(
                    _("This bank account is already added to your wallet")
                )
        
        return attrs


class BankAccountUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating bank account information
    
    Allows updating specific fields while protecting critical data.
    """
    
    class Meta:
        model = BankAccount
        fields = [
            'account_name',
            'account_type',
            'is_default',
            'is_active'
        ]
        extra_kwargs = {
            'account_name': {
                'help_text': _('Update account holder name')
            },
            'account_type': {
                'help_text': _('Update account type')
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
        # If setting to False, ensure there's another default account
        if not value and self.instance.is_default:
            wallet = self.instance.wallet
            other_defaults = BankAccount.objects.filter(
                wallet=wallet,
                is_default=True,
                is_active=True
            ).exclude(pk=self.instance.pk).count()
            
            if other_defaults == 0:
                raise serializers.ValidationError(
                    _("Cannot unset default. Please set another account as default first.")
                )
        
        return value


class BankAccountVerifySerializer(serializers.Serializer):
    """
    Serializer for verifying bank account details with Paystack
    
    Used to verify account name before adding to wallet.
    """
    
    account_number = serializers.CharField(
        max_length=20,
        help_text=_('Bank account number to verify')
    )
    bank_code = serializers.CharField(
        max_length=20,
        help_text=_('Bank code')
    )
    
    def validate_account_number(self, value):
        """Validate account number format"""
        value = value.replace(' ', '').replace('-', '')
        
        if not value.isdigit():
            raise serializers.ValidationError(
                _("Account number must contain only digits")
            )
        
        if len(value) < 10 or len(value) > 20:
            raise serializers.ValidationError(
                _("Account number must be between 10 and 20 digits")
            )
        
        return value
    
    def validate_bank_code(self, value):
        """Validate bank code exists"""
        try:
            Bank.objects.get(code=value, is_active=True)
        except Bank.DoesNotExist:
            raise serializers.ValidationError(
                _("Invalid or inactive bank code")
            )
        return value


class BankAccountSetDefaultSerializer(serializers.Serializer):
    """
    Serializer for setting a bank account as default
    
    Simple serializer for the set_default action.
    """
    
    pass  # No additional fields needed


class BankAccountStatisticsSerializer(serializers.Serializer):
    """
    Serializer for bank account statistics
    
    Provides comprehensive statistics for a bank account.
    """
    
    # Account info
    id = serializers.UUIDField(read_only=True)
    account_name = serializers.CharField(read_only=True)
    account_number = serializers.CharField(read_only=True)
    bank_name = serializers.CharField(read_only=True)
    
    # Statistics
    total_transactions = serializers.IntegerField(read_only=True)
    successful_transactions = serializers.IntegerField(read_only=True)
    total_settlements = serializers.IntegerField(read_only=True)
    successful_settlements = serializers.IntegerField(read_only=True)
    total_settled_amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=2,
        read_only=True
    )
    
    # Status
    is_default = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)