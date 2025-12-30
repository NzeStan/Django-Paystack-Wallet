import datetime
from decimal import Decimal
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from wallet.constants import FEE_BEARERS
from wallet.models import Wallet


# ==========================================
# BASE WALLET SERIALIZERS
# ==========================================

class WalletSerializer(serializers.ModelSerializer):
    """
    Base serializer for Wallet model
    
    Provides read-only access to core wallet data with proper
    field formatting and validation.
    """
    
    # User Information
    user_id = serializers.CharField(source='user.id', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField(read_only=True)
    
    # Balance Information
    balance_amount = serializers.DecimalField(
        source='balance.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True,
        help_text=_('Current wallet balance amount')
    )
    balance_currency = serializers.CharField(
        source='balance.currency.code',
        read_only=True,
        help_text=_('Wallet currency code')
    )
    available_balance = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Available balance (same as current balance)')
    )
    
    # Daily Transaction Metrics
    daily_transaction_total_amount = serializers.DecimalField(
        source='daily_transaction_total.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True,
        help_text=_('Total amount transacted today')
    )
    daily_transaction_reset = serializers.SerializerMethodField(
        help_text=_('Date when daily limits will reset')
    )
    
    # Status Information
    is_operational = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Whether wallet can perform operations')
    )
    
    class Meta:
        model = Wallet
        fields = [
            # Identifiers
            'id',
            'user_id',
            'user',
            'user_email',
            'user_name',
            'tag',
            
            # Balance
            'balance_amount',
            'balance_currency',
            'available_balance',
            
            # Status
            'is_active',
            'is_locked',
            'is_operational',
            
            # Transaction Metrics
            'last_transaction_date',
            'daily_transaction_total_amount',
            'daily_transaction_count',
            'daily_transaction_reset',
            
            # Paystack Integration
            'dedicated_account_number',
            'dedicated_account_bank',
            
            # Timestamps
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user',
            'user_id',
            'user_email',
            'user_name',
            'balance_amount',
            'balance_currency',
            'available_balance',
            'last_transaction_date',
            'daily_transaction_total_amount',
            'daily_transaction_count',
            'daily_transaction_reset',
            'is_operational',
            'dedicated_account_number',
            'dedicated_account_bank',
            'created_at',
            'updated_at',
        ]
    
    def get_user_name(self, wallet: Wallet) -> str:
        """
        Get user's full name or fallback to username/email
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            str: User's display name
        """
        user = wallet.user
        
        # Try to get full name
        if hasattr(user, 'get_full_name'):
            full_name = user.get_full_name()
            if full_name and full_name.strip():
                return full_name
        
        # Try name attribute
        if hasattr(user, 'name') and user.name:
            return user.name
        
        # Try first_name and last_name
        if hasattr(user, 'first_name') and hasattr(user, 'last_name'):
            name = f"{user.first_name} {user.last_name}".strip()
            if name:
                return name
        
        # Fall back to username
        if hasattr(user, 'username') and user.username:
            return user.username
        
        # Last resort - email or None
        if hasattr(user, 'email') and user.email:
            return user.email
        
        return None
    
    def get_daily_transaction_reset(self, wallet: Wallet):
        """
        Get the daily transaction reset date
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            date or None: Reset date
        """
        if wallet.daily_transaction_reset:
            # Ensure we return a date object, not datetime
            if isinstance(wallet.daily_transaction_reset, datetime.datetime):
                return wallet.daily_transaction_reset.date()
            return wallet.daily_transaction_reset
        return None
    
    def get_available_balance(self, wallet: Wallet) -> Decimal:
        """
        Get available balance for transactions
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            Decimal: Available balance amount
        """
        return wallet.balance.amount
    
    def get_is_operational(self, wallet: Wallet) -> bool:
        """
        Check if wallet can perform operations
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            bool: True if wallet is operational
        """
        return wallet.is_operational


class WalletDetailSerializer(WalletSerializer):
    """
    Detailed serializer for Wallet model
    
    Extends base serializer with additional computed fields
    and relationship counts.
    """
    
    # Transaction Statistics
    transaction_count = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Total number of transactions')
    )
    successful_transactions = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Number of successful transactions')
    )
    pending_transactions = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Number of pending transactions')
    )
    
    # Related Objects Count
    cards_count = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Number of active cards')
    )
    bank_accounts_count = serializers.SerializerMethodField(
        read_only=True,
        help_text=_('Number of active bank accounts')
    )
    
    # Paystack Customer
    paystack_customer_code = serializers.CharField(
        read_only=True,
        help_text=_('Paystack customer identifier')
    )
    
    class Meta(WalletSerializer.Meta):
        fields = WalletSerializer.Meta.fields + [
            'transaction_count',
            'successful_transactions',
            'pending_transactions',
            'cards_count',
            'bank_accounts_count',
            'paystack_customer_code',
        ]
        read_only_fields = WalletSerializer.Meta.read_only_fields + [
            'transaction_count',
            'successful_transactions',
            'pending_transactions',
            'cards_count',
            'bank_accounts_count',
            'paystack_customer_code',
        ]
    
    def get_transaction_count(self, wallet: Wallet) -> int:
        """
        Get total transaction count
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            int: Total transactions
        """
        return wallet.transactions.count()
    
    def get_successful_transactions(self, wallet: Wallet) -> int:
        """
        Get successful transaction count
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            int: Successful transactions
        """
        from wallet.constants import TRANSACTION_STATUS_SUCCESS
        return wallet.transactions.filter(status=TRANSACTION_STATUS_SUCCESS).count()
    
    def get_pending_transactions(self, wallet: Wallet) -> int:
        """
        Get pending transaction count
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            int: Pending transactions
        """
        from wallet.constants import TRANSACTION_STATUS_PENDING
        return wallet.transactions.filter(status=TRANSACTION_STATUS_PENDING).count()
    
    def get_cards_count(self, wallet: Wallet) -> int:
        """
        Get active cards count
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            int: Number of active cards
        """
        return wallet.cards.filter(is_active=True).count()
    
    def get_bank_accounts_count(self, wallet: Wallet) -> int:
        """
        Get active bank accounts count
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            int: Number of active bank accounts
        """
        return wallet.bank_accounts.filter(is_active=True).count()


class WalletCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating wallets
    
    Allows modification of limited fields that users can control.
    """
    
    class Meta:
        model = Wallet
        fields = ['tag', 'is_active', 'is_locked']
    
    def validate_tag(self, value):
        """
        Validate wallet tag
        
        Args:
            value (str): Tag value
            
        Returns:
            str: Validated tag
            
        Raises:
            ValidationError: If tag is invalid
        """
        if value:
            # Remove extra whitespace
            value = value.strip()
            
            # Check length
            if len(value) > 100:
                raise serializers.ValidationError(
                    _("Tag must be 100 characters or less")
                )
            
            # Check for invalid characters (optional - customize as needed)
            if not value.replace('_', '').replace('-', '').replace(' ', '').isalnum():
                raise serializers.ValidationError(
                    _("Tag can only contain letters, numbers, spaces, hyphens, and underscores")
                )
        
        return value


# ==========================================
# TRANSACTION OPERATION SERIALIZERS
# ==========================================

class WalletTransactionSerializer(serializers.Serializer):
    """
    Base serializer for wallet transaction operations
    
    Provides common fields and validation for deposits, withdrawals, etc.
    """
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01"),
        required=True,
        help_text=_('Transaction amount (must be positive)')
    )
    
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text=_('Optional transaction description')
    )
    
    reference = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text=_('Optional custom transaction reference')
    )
    
    metadata = serializers.JSONField(
        required=False,
        help_text=_('Optional additional data as JSON')
    )
    

    fee_bearer = serializers.ChoiceField(
        choices=FEE_BEARERS,  # Use the constant
        required=False,
        allow_null=True,
        help_text=_('Who bears the transaction fee (defaults to system setting if not provided)')
    )


    def validate_amount(self, value: Decimal) -> Decimal:
        """
        Validate transaction amount
        
        Args:
            value (Decimal): Amount to validate
            
        Returns:
            Decimal: Validated amount
            
        Raises:
            ValidationError: If amount is invalid
        """
        if value <= 0:
            raise serializers.ValidationError(
                _("Amount must be greater than zero")
            )
        
        # Check for reasonable maximum (optional - adjust as needed)
        max_amount = Decimal("999999999.99")
        if value > max_amount:
            raise serializers.ValidationError(
                _("Amount exceeds maximum allowed value")
            )
        
        return value
    
    def validate_reference(self, value: str) -> str:
        """
        Validate transaction reference
        
        Args:
            value (str): Reference to validate
            
        Returns:
            str: Validated reference
            
        Raises:
            ValidationError: If reference is invalid
        """
        if value:
            value = value.strip()
            
            # Check length
            if len(value) > 100:
                raise serializers.ValidationError(
                    _("Reference must be 100 characters or less")
                )
            
            # Check for valid characters (alphanumeric, dash, underscore)
            if not value.replace('-', '').replace('_', '').isalnum():
                raise serializers.ValidationError(
                    _("Reference can only contain letters, numbers, hyphens, and underscores")
                )
        
        return value
    
    def validate_metadata(self, value: dict) -> dict:
        """
        Validate metadata
        
        Args:
            value (dict): Metadata to validate
            
        Returns:
            dict: Validated metadata
            
        Raises:
            ValidationError: If metadata is invalid
        """
        if value is not None:
            if not isinstance(value, dict):
                raise serializers.ValidationError(
                    _("Metadata must be a JSON object")
                )
        
        return value or {}


class WalletDepositSerializer(WalletTransactionSerializer):
    """
    Serializer for wallet deposit operations
    
    Extends base transaction serializer with deposit-specific fields.
    """
    
    callback_url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text=_('URL to redirect to after payment')
    )
    
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        help_text=_('Customer email (defaults to user email)')
    )
    
    def validate_email(self, value: str) -> str:
        """
        Validate email
        
        Args:
            value (str): Email to validate
            
        Returns:
            str: Validated email
            
        Raises:
            ValidationError: If email is invalid
        """
        if value:
            value = value.strip().lower()
        return value


class WalletWithdrawSerializer(WalletTransactionSerializer):
    """
    Serializer for wallet withdrawal operations
    
    Extends base transaction serializer with withdrawal-specific fields.
    """
    
    bank_account_id = serializers.CharField(
        required=True,
        help_text=_('ID of the bank account to withdraw to')
    )
    
    def validate_bank_account_id(self, value: str) -> str:
        """
        Validate bank account ID
        
        Args:
            value (str): Bank account ID
            
        Returns:
            str: Validated bank account ID
            
        Raises:
            ValidationError: If bank account ID is invalid
        """
        if not value or not value.strip():
            raise serializers.ValidationError(
                _("Bank account ID is required")
            )
        
        return value.strip()


class WalletTransferSerializer(WalletTransactionSerializer):
    """
    Serializer for wallet transfer operations
    
    Extends base transaction serializer with transfer-specific fields.
    """
    
    destination_wallet_id = serializers.CharField(
        required=True,
        help_text=_('ID of the wallet to transfer to')
    )
    
    def validate_destination_wallet_id(self, value: str) -> str:
        """
        Validate destination wallet ID
        
        Args:
            value (str): Destination wallet ID
            
        Returns:
            str: Validated destination wallet ID
            
        Raises:
            ValidationError: If wallet ID is invalid
        """
        if not value or not value.strip():
            raise serializers.ValidationError(
                _("Destination wallet ID is required")
            )
        
        return value.strip()
    
    def validate(self, attrs: dict) -> dict:
        """
        Validate transfer data
        
        Args:
            attrs (dict): Serializer data
            
        Returns:
            dict: Validated data
            
        Raises:
            ValidationError: If data is invalid
        """
        # Ensure destination wallet is provided
        if 'destination_wallet_id' not in attrs or not attrs['destination_wallet_id']:
            raise serializers.ValidationError({
                'destination_wallet_id': _("Destination wallet ID is required")
            })
        
        return attrs


class FinalizeWithdrawalSerializer(serializers.Serializer):
    """
    Serializer for finalizing withdrawal with OTP
    
    Validates OTP and transfer code
    """
    transfer_code = serializers.CharField(
        max_length=50,
        help_text=_("Transfer code from initial withdrawal response")
    )
    
    otp = serializers.CharField(
        min_length=4,
        max_length=10,
        help_text=_("One-Time Password received by user")
    )
    
    def validate_transfer_code(self, value):
        """Validate transfer code format"""
        if not value:
            raise serializers.ValidationError(
                _("Transfer code is required")
            )
        
        # Paystack transfer codes typically start with TRF_
        if not value.startswith('TRF_'):
            raise serializers.ValidationError(
                _("Invalid transfer code format. Must start with 'TRF_'")
            )
        
        return value
    
    def validate_otp(self, value):
        """Validate OTP format"""
        if not value:
            raise serializers.ValidationError(
                _("OTP is required")
            )
        
        # OTP should be numeric
        if not value.isdigit():
            raise serializers.ValidationError(
                _("OTP must contain only numbers")
            )
        
        # OTP is typically 6 digits for Paystack
        if len(value) < 4 or len(value) > 10:
            raise serializers.ValidationError(
                _("OTP must be between 4 and 10 digits")
            )
        
        return value



# ==========================================
# BALANCE QUERY SERIALIZER
# ==========================================

class WalletBalanceSerializer(serializers.Serializer):
    """
    Serializer for wallet balance responses
    
    Provides a simple, focused view of wallet balance.
    """
    
    balance_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    
    balance_currency = serializers.CharField(read_only=True)
    
    available_balance = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    
    is_operational = serializers.BooleanField(read_only=True)
    
    last_updated = serializers.DateTimeField(read_only=True)