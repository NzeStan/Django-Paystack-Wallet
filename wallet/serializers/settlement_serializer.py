"""
Django Paystack Wallet - Settlement Serializers
Comprehensive serializers with validation and optimization
"""
from decimal import Decimal
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.models import (
    Settlement,
    SettlementSchedule,
    BankAccount,
    Wallet
)
from wallet.constants import (
    SETTLEMENT_STATUS_PENDING,
    SETTLEMENT_STATUS_PROCESSING,
    SETTLEMENT_STATUS_SUCCESS,
    SETTLEMENT_STATUS_FAILED
)


# ==========================================
# SETTLEMENT SERIALIZERS
# ==========================================


class SettlementSerializer(serializers.ModelSerializer):
    """
    Standard serializer for the Settlement model
    
    Provides read-only representation with related data.
    """
    
    # Related IDs
    wallet_id = serializers.CharField(
        source='wallet.id',
        read_only=True
    )
    bank_account_id = serializers.CharField(
        source='bank_account.id',
        read_only=True
    )
    transaction_id = serializers.CharField(
        source='transaction.id',
        read_only=True,
        allow_null=True
    )
    
    # Bank account details
    bank_account_name = serializers.CharField(
        source='bank_account.account_name',
        read_only=True
    )
    bank_account_number = serializers.CharField(
        source='bank_account.account_number',
        read_only=True
    )
    bank_name = serializers.CharField(
        source='bank_account.bank.name',
        read_only=True
    )
    bank_code = serializers.CharField(
        source='bank_account.bank.code',
        read_only=True
    )
    
    # Money field decomposition
    amount_value = serializers.DecimalField(
        source='amount.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    amount_currency = serializers.CharField(
        source='amount.currency.code',
        read_only=True
    )
    fees_value = serializers.DecimalField(
        source='fees.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    fees_currency = serializers.CharField(
        source='fees.currency.code',
        read_only=True
    )
    
    # Display fields
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    
    # Computed fields
    net_amount = serializers.SerializerMethodField()
    processing_time = serializers.SerializerMethodField()
    is_completed = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Settlement
        fields = [
            # Core fields
            'id',
            'wallet_id',
            'bank_account_id',
            'transaction_id',
            
            # Bank account details
            'bank_account_name',
            'bank_account_number',
            'bank_name',
            'bank_code',
            
            # Amount fields
            'amount_value',
            'amount_currency',
            'fees_value',
            'fees_currency',
            'net_amount',
            
            # Status fields
            'status',
            'status_display',
            'is_completed',
            
            # Reference fields
            'reference',
            'paystack_transfer_code',
            
            # Additional fields
            'reason',
            'metadata',
            
            # Timestamps
            'created_at',
            'updated_at',
            'settled_at',
            'processing_time',
            
            # Failure info
            'failure_reason',
        ]
        read_only_fields = fields
    
    def get_net_amount(self, obj):
        """Calculate net amount (amount - fees)"""
        net = obj.net_amount
        return {
            'value': float(net.amount),
            'currency': net.currency.code
        }
    
    def get_processing_time(self, obj):
        """Get processing time in seconds"""
        if obj.processing_time:
            return obj.processing_time.total_seconds()
        return None


class SettlementDetailSerializer(SettlementSerializer):
    """
    Detailed serializer for the Settlement model
    
    Includes all fields including Paystack transfer data.
    """
    
    # Include Paystack data
    paystack_transfer_data = serializers.JSONField(read_only=True)
    
    # Transaction details
    transaction_reference = serializers.CharField(
        source='transaction.reference',
        read_only=True,
        allow_null=True
    )
    transaction_status = serializers.CharField(
        source='transaction.status',
        read_only=True,
        allow_null=True
    )
    
    # Wallet details
    wallet_balance = serializers.SerializerMethodField()
    
    class Meta(SettlementSerializer.Meta):
        fields = SettlementSerializer.Meta.fields + [
            'paystack_transfer_data',
            'transaction_reference',
            'transaction_status',
            'wallet_balance',
        ]
        read_only_fields = fields
    
    def get_wallet_balance(self, obj):
        """Get current wallet balance"""
        balance = obj.wallet.balance
        return {
            'value': float(balance.amount),
            'currency': balance.currency.code
        }


class SettlementListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for settlement lists
    
    Optimized for list views with minimal data.
    """
    
    amount = serializers.SerializerMethodField()
    bank_account = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    
    class Meta:
        model = Settlement
        fields = [
            'id',
            'amount',
            'bank_account',
            'status',
            'status_display',
            'reference',
            'created_at',
            'settled_at',
        ]
        read_only_fields = fields
    
    def get_amount(self, obj):
        """Get formatted amount"""
        return {
            'value': float(obj.amount.amount),
            'currency': obj.amount.currency.code
        }
    
    def get_bank_account(self, obj):
        """Get bank account summary"""
        return {
            'id': str(obj.bank_account.id),
            'account_number': obj.bank_account.account_number,
            'bank_name': obj.bank_account.bank.name
        }


class SettlementCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a settlement
    
    Validates input and prepares data for settlement creation.
    """
    
    bank_account_id = serializers.CharField(
        required=True,
        help_text=_('ID of the bank account to settle to')
    )
    
    amount = serializers.DecimalField(
        required=True,
        decimal_places=2,
        max_digits=19,
        min_value=Decimal('0.01'),
        help_text=_('Amount to settle')
    )
    
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=_('Reason for settlement')
    )
    
    metadata = serializers.JSONField(
        required=False,
        help_text=_('Additional metadata')
    )
    
    def __init__(self, *args, **kwargs):
        """
        Initialize serializer with optional wallet context
        
        Args:
            wallet: Wallet instance (passed via context)
        """
        self.wallet = kwargs.pop('wallet', None)
        
        # Also check context for wallet
        if not self.wallet and 'context' in kwargs:
            self.wallet = kwargs['context'].get('wallet')
        
        super().__init__(*args, **kwargs)
    
    def validate_bank_account_id(self, value):
        """
        Validate bank account exists, is active, and belongs to user's wallet
        
        Args:
            value: Bank account ID
            
        Returns:
            str: Validated bank account ID
            
        Raises:
            ValidationError: If bank account is invalid
        """
        try:
            bank_account = BankAccount.objects.get(id=value)
            
            # Check if bank account belongs to the user's wallet
            if self.wallet and bank_account.wallet != self.wallet:
                raise serializers.ValidationError(
                    _("Bank account not found")
                )
            
            # Check if bank account is active
            if not bank_account.is_active:
                raise serializers.ValidationError(
                    _("Bank account is inactive")
                )
            
            # Check if bank account is verified
            if not bank_account.is_verified:
                raise serializers.ValidationError(
                    _("Bank account is not verified")
                )
            
            # Check if bank account has recipient code
            if not bank_account.paystack_recipient_code:
                raise serializers.ValidationError(
                    _("Bank account does not have a recipient code")
                )
            
            return value
            
        except BankAccount.DoesNotExist:
            raise serializers.ValidationError(
                _("Bank account not found")
            )
    
    def validate_amount(self, value):
        """
        Validate amount is positive and within limits
        
        Args:
            value: Amount to validate
            
        Returns:
            Decimal: Validated amount
            
        Raises:
            ValidationError: If amount is invalid
        """
        if value <= 0:
            raise serializers.ValidationError(
                _("Amount must be greater than zero")
            )
        
        # Validate against wallet balance if wallet is provided
        if self.wallet:
            wallet_balance = self.wallet.balance.amount
            
            if value > wallet_balance:
                raise serializers.ValidationError(
                    _("Insufficient funds. Wallet balance: %(balance)s") % {
                        'balance': wallet_balance
                    }
                )
            
            # Check minimum balance requirement
            from wallet.settings import get_wallet_setting
            minimum_balance = Decimal(str(get_wallet_setting('MINIMUM_BALANCE')))
            
            if wallet_balance - value < minimum_balance:
                raise serializers.ValidationError(
                    _("Settlement would leave wallet below minimum balance of %(min)s") % {
                        'min': minimum_balance
                    }
                )
        
        return value
    
    def validate(self, attrs):
        """
        Perform cross-field validation
        
        Args:
            attrs: Attribute dictionary
            
        Returns:
            dict: Validated attributes
        """
        # Additional validation can be added here
        return attrs


class SettlementUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a settlement
    
    Only allows updating limited fields.
    """
    
    class Meta:
        model = Settlement
        fields = [
            'reason',
            'metadata',
        ]
    
    def validate(self, attrs):
        """
        Validate that settlement can be updated
        
        Args:
            attrs: Attribute dictionary
            
        Returns:
            dict: Validated attributes
            
        Raises:
            ValidationError: If settlement cannot be updated
        """
        # Only allow updates to pending settlements
        if self.instance and not self.instance.is_pending:
            raise serializers.ValidationError(
                _("Only pending settlements can be updated")
            )
        
        return attrs


class SettlementStatusSerializer(serializers.Serializer):
    """
    Serializer for settlement status checks
    
    Used for status verification endpoints.
    """
    
    reference = serializers.CharField(
        required=False,
        help_text=_('Settlement reference')
    )
    
    paystack_transfer_code = serializers.CharField(
        required=False,
        help_text=_('Paystack transfer code')
    )
    
    def validate(self, attrs):
        """
        Validate that at least one identifier is provided
        
        Args:
            attrs: Attribute dictionary
            
        Returns:
            dict: Validated attributes
            
        Raises:
            ValidationError: If no identifier is provided
        """
        if not attrs.get('reference') and not attrs.get('paystack_transfer_code'):
            raise serializers.ValidationError(
                _("Either reference or paystack_transfer_code must be provided")
            )
        
        return attrs


# ==========================================
# SETTLEMENT SCHEDULE SERIALIZERS
# ==========================================


class SettlementScheduleSerializer(serializers.ModelSerializer):
    """
    Standard serializer for the SettlementSchedule model
    
    Provides read-only representation with related data.
    """
    
    # Related IDs
    wallet_id = serializers.CharField(
        source='wallet.id',
        read_only=True
    )
    bank_account_id = serializers.CharField(
        source='bank_account.id',
        read_only=True
    )
    
    # Bank account details
    bank_account_name = serializers.CharField(
        source='bank_account.account_name',
        read_only=True
    )
    bank_account_number = serializers.CharField(
        source='bank_account.account_number',
        read_only=True
    )
    bank_name = serializers.CharField(
        source='bank_account.bank.name',
        read_only=True
    )
    
    # Display fields
    schedule_type_display = serializers.CharField(
        source='get_schedule_type_display',
        read_only=True
    )
    
    # Money field decomposition
    amount_threshold_value = serializers.DecimalField(
        source='amount_threshold.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True,
        allow_null=True
    )
    minimum_amount_value = serializers.DecimalField(
        source='minimum_amount.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    maximum_amount_value = serializers.DecimalField(
        source='maximum_amount.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True,
        allow_null=True
    )
    
    # Day of week display
    day_of_week_display = serializers.SerializerMethodField(read_only=True)
    
    # Computed fields
    is_due = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = SettlementSchedule
        fields = [
            # Core fields
            'id',
            'wallet_id',
            'bank_account_id',
            
            # Bank account details
            'bank_account_name',
            'bank_account_number',
            'bank_name',
            
            # Schedule settings
            'is_active',
            'schedule_type',
            'schedule_type_display',
            
            # Amount settings
            'amount_threshold_value',
            'minimum_amount_value',
            'maximum_amount_value',
            
            # Timing settings
            'day_of_week',
            'day_of_week_display',
            'day_of_month',
            'time_of_day',
            
            # Tracking fields
            'last_settlement',
            'next_settlement',
            'is_due',
            
            # Timestamps
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'wallet_id',
            'bank_account_id',
            'bank_account_name',
            'bank_account_number',
            'bank_name',
            'schedule_type_display',
            'day_of_week_display',
            'is_due',
            'created_at',
            'updated_at',
            'last_settlement',
            'next_settlement',
        ]
    
    def get_day_of_week_display(self, obj):
        """
        Get display value for day of week
        
        Args:
            obj: SettlementSchedule instance
            
        Returns:
            str: Day of week name or None
        """
        if obj.day_of_week is None:
            return None
        
        days = [
            _('Monday'),
            _('Tuesday'),
            _('Wednesday'),
            _('Thursday'),
            _('Friday'),
            _('Saturday'),
            _('Sunday')
        ]
        
        return days[obj.day_of_week]


class SettlementScheduleCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a settlement schedule
    
    Validates input and prepares data for schedule creation.
    """
    
    bank_account_id = serializers.CharField(
        write_only=True,
        required=True,
        help_text=_('ID of the bank account to settle to')
    )
    
    amount_threshold = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False,
        allow_null=True,
        help_text=_('Threshold amount for threshold-based settlements')
    )
    
    minimum_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        default=0,
        help_text=_('Minimum amount to settle')
    )
    
    maximum_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False,
        allow_null=True,
        help_text=_('Maximum amount to settle (optional)')
    )
    
    class Meta:
        model = SettlementSchedule
        fields = [
            'bank_account_id',
            'schedule_type',
            'is_active',
            'amount_threshold',
            'minimum_amount',
            'maximum_amount',
            'day_of_week',
            'day_of_month',
            'time_of_day',
        ]
    
    def validate_bank_account_id(self, value):
        """
        Validate bank account exists and is active
        
        Args:
            value: Bank account ID
            
        Returns:
            str: Validated bank account ID
            
        Raises:
            ValidationError: If bank account is invalid
        """
        try:
            bank_account = BankAccount.objects.get(id=value)
            
            # Check if bank account is active
            if not bank_account.is_active:
                raise serializers.ValidationError(
                    _("Bank account is inactive")
                )
            
            # Check if bank account is verified
            if not bank_account.is_verified:
                raise serializers.ValidationError(
                    _("Bank account is not verified")
                )
            
            return value
            
        except BankAccount.DoesNotExist:
            raise serializers.ValidationError(
                _("Bank account not found")
            )
    
    def validate_day_of_week(self, value):
        """
        Validate day of week is in valid range
        
        Args:
            value: Day of week
            
        Returns:
            int: Validated day of week
            
        Raises:
            ValidationError: If day of week is invalid
        """
        if value is not None and not (0 <= value <= 6):
            raise serializers.ValidationError(
                _("Day of week must be between 0 (Monday) and 6 (Sunday)")
            )
        
        return value
    
    def validate_day_of_month(self, value):
        """
        Validate day of month is in valid range
        
        Args:
            value: Day of month
            
        Returns:
            int: Validated day of month
            
        Raises:
            ValidationError: If day of month is invalid
        """
        if value is not None and not (1 <= value <= 31):
            raise serializers.ValidationError(
                _("Day of month must be between 1 and 31")
            )
        
        return value
    
    def validate(self, attrs):
        """
        Perform cross-field validation
        
        Args:
            attrs: Attribute dictionary
            
        Returns:
            dict: Validated attributes
            
        Raises:
            ValidationError: If validation fails
        """
        schedule_type = attrs.get('schedule_type')
        
        # Validate weekly schedule has day_of_week
        if schedule_type == 'weekly' and not attrs.get('day_of_week'):
            raise serializers.ValidationError({
                'day_of_week': _("Day of week is required for weekly schedules")
            })
        
        # Validate monthly schedule has day_of_month
        if schedule_type == 'monthly' and not attrs.get('day_of_month'):
            raise serializers.ValidationError({
                'day_of_month': _("Day of month is required for monthly schedules")
            })
        
        # Validate threshold schedule has amount_threshold
        if schedule_type == 'threshold' and not attrs.get('amount_threshold'):
            raise serializers.ValidationError({
                'amount_threshold': _("Amount threshold is required for threshold-based schedules")
            })
        
        # Validate minimum_amount is less than maximum_amount if both provided
        minimum = attrs.get('minimum_amount')
        maximum = attrs.get('maximum_amount')
        
        if minimum and maximum and minimum >= maximum:
            raise serializers.ValidationError({
                'maximum_amount': _("Maximum amount must be greater than minimum amount")
            })
        
        return attrs


class SettlementScheduleUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a settlement schedule
    
    Allows updating schedule configuration.
    """
    
    amount_threshold = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False,
        allow_null=True
    )
    
    minimum_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False
    )
    
    maximum_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = SettlementSchedule
        fields = [
            'is_active',
            'amount_threshold',
            'minimum_amount',
            'maximum_amount',
            'day_of_week',
            'day_of_month',
            'time_of_day',
        ]
    
    def validate(self, attrs):
        """
        Perform cross-field validation
        
        Args:
            attrs: Attribute dictionary
            
        Returns:
            dict: Validated attributes
        """
        # Get current schedule type from instance
        schedule_type = self.instance.schedule_type
        
        # Validate weekly schedule has day_of_week
        if schedule_type == 'weekly':
            day_of_week = attrs.get('day_of_week', self.instance.day_of_week)
            if day_of_week is None:
                raise serializers.ValidationError({
                    'day_of_week': _("Day of week is required for weekly schedules")
                })
        
        # Validate monthly schedule has day_of_month
        if schedule_type == 'monthly':
            day_of_month = attrs.get('day_of_month', self.instance.day_of_month)
            if day_of_month is None:
                raise serializers.ValidationError({
                    'day_of_month': _("Day of month is required for monthly schedules")
                })
        
        # Validate threshold schedule has amount_threshold
        if schedule_type == 'threshold':
            threshold = attrs.get('amount_threshold', self.instance.amount_threshold)
            if threshold is None:
                raise serializers.ValidationError({
                    'amount_threshold': _("Amount threshold is required for threshold-based schedules")
                })
        
        return attrs


class SettlementScheduleListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for settlement schedule lists
    
    Optimized for list views with minimal data.
    """
    
    schedule_type_display = serializers.CharField(
        source='get_schedule_type_display',
        read_only=True
    )
    bank_account = serializers.SerializerMethodField()
    
    class Meta:
        model = SettlementSchedule
        fields = [
            'id',
            'is_active',
            'schedule_type',
            'schedule_type_display',
            'bank_account',
            'next_settlement',
            'created_at',
        ]
        read_only_fields = fields
    
    def get_bank_account(self, obj):
        """Get bank account summary"""
        return {
            'id': str(obj.bank_account.id),
            'account_number': obj.bank_account.account_number,
            'bank_name': obj.bank_account.bank.name
        }


# ==========================================
# EXPORT SERIALIZERS
# ==========================================


class SettlementExportSerializer(serializers.ModelSerializer):
    """
    Serializer for exporting settlements
    
    Includes all relevant fields for export formats (CSV/Excel).
    """
    
    wallet_id = serializers.CharField(source='wallet.id')
    wallet_user_email = serializers.EmailField(source='wallet.user.email')
    bank_account_number = serializers.CharField(source='bank_account.account_number')
    bank_name = serializers.CharField(source='bank_account.bank.name')
    amount_value = serializers.DecimalField(
        source='amount.amount',
        decimal_places=2,
        max_digits=19
    )
    amount_currency = serializers.CharField(source='amount.currency.code')
    fees_value = serializers.DecimalField(
        source='fees.amount',
        decimal_places=2,
        max_digits=19
    )
    status_display = serializers.CharField(source='get_status_display')
    
    class Meta:
        model = Settlement
        fields = [
            'id',
            'wallet_id',
            'wallet_user_email',
            'bank_account_number',
            'bank_name',
            'amount_value',
            'amount_currency',
            'fees_value',
            'status',
            'status_display',
            'reference',
            'paystack_transfer_code',
            'reason',
            'created_at',
            'settled_at',
            'failure_reason',
        ]