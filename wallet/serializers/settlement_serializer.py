from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from wallet.models import Settlement, SettlementSchedule, BankAccount


class SettlementSerializer(serializers.ModelSerializer):
    """Serializer for the Settlement model"""
    
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
    bank_account_id = serializers.CharField(source='bank_account.id', read_only=True)
    bank_account_name = serializers.CharField(source='bank_account.account_name', read_only=True)
    bank_account_number = serializers.CharField(source='bank_account.account_number', read_only=True)
    bank_name = serializers.CharField(source='bank_account.bank.name', read_only=True)
    amount_value = serializers.DecimalField(
        source='amount.amount', 
        decimal_places=2, 
        max_digits=19, 
        read_only=True
    )
    amount_currency = serializers.CharField(source='amount.currency.code', read_only=True)
    fees_value = serializers.DecimalField(
        source='fees.amount', 
        decimal_places=2, 
        max_digits=19, 
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    transaction_id = serializers.CharField(source='transaction.id', read_only=True)
    
    class Meta:
        model = Settlement
        fields = [
            'id', 'wallet_id', 'bank_account_id', 'bank_account_name',
            'bank_account_number', 'bank_name', 'amount_value', 'amount_currency',
            'fees_value', 'status', 'status_display', 'reference',
            'paystack_transfer_code', 'reason', 'metadata',
            'transaction_id', 'created_at', 'updated_at', 'settled_at',
            'failure_reason'
        ]
        read_only_fields = fields


class SettlementDetailSerializer(SettlementSerializer):
    """Detailed serializer for the Settlement model"""
    
    paystack_transfer_data = serializers.JSONField(read_only=True)
    
    class Meta(SettlementSerializer.Meta):
        fields = SettlementSerializer.Meta.fields + ['paystack_transfer_data']
        read_only_fields = fields


class SettlementCreateSerializer(serializers.Serializer):
    """Serializer for creating a settlement"""
    
    bank_account_id = serializers.CharField()
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal('0.01')
    )
    reason = serializers.CharField(required=False)
    metadata = serializers.JSONField(required=False)
    
    def __init__(self, *args, **kwargs):
        # Accept wallet context
        self.wallet = kwargs.pop('wallet', None)
        super().__init__(*args, **kwargs)
    
    def validate_bank_account_id(self, value):
        """Validate bank account exists, is active, and belongs to user's wallet"""
        try:
            bank_account = BankAccount.objects.get(id=value)
            
            # Check if bank account belongs to the user's wallet
            if self.wallet and bank_account.wallet != self.wallet:
                raise serializers.ValidationError(_("Bank account not found"))
            
            if not bank_account.is_active:
                raise serializers.ValidationError(_("Bank account is inactive"))
            if not bank_account.is_verified:
                raise serializers.ValidationError(_("Bank account is not verified"))
            if not bank_account.paystack_recipient_code:
                raise serializers.ValidationError(_("Bank account does not have a recipient code"))
            
            return value
        except BankAccount.DoesNotExist:
            raise serializers.ValidationError(_("Bank account not found"))
    
    def validate_amount(self, value):
        """Validate amount is positive"""
        if value <= 0:
            raise serializers.ValidationError(_("Amount must be greater than zero"))
        return value


class SettlementScheduleSerializer(serializers.ModelSerializer):
    """Serializer for the SettlementSchedule model"""
    
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
    bank_account_id = serializers.CharField(source='bank_account.id', read_only=True)
    bank_account_name = serializers.CharField(source='bank_account.account_name', read_only=True)
    bank_account_number = serializers.CharField(source='bank_account.account_number', read_only=True)
    bank_name = serializers.CharField(source='bank_account.bank.name', read_only=True)
    schedule_type_display = serializers.CharField(source='get_schedule_type_display', read_only=True)
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
    day_of_week_display = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = SettlementSchedule
        fields = [
            'id', 'wallet_id', 'bank_account_id', 'bank_account_name',
            'bank_account_number', 'bank_name', 'is_active',
            'schedule_type', 'schedule_type_display',
            'amount_threshold_value', 'minimum_amount_value', 'maximum_amount_value',
            'day_of_week', 'day_of_week_display', 'day_of_month', 'time_of_day',
            'last_settlement', 'next_settlement',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'wallet_id', 'bank_account_name', 'bank_account_number',
            'bank_name', 'schedule_type_display', 'day_of_week_display',
            'created_at', 'updated_at', 'last_settlement', 'next_settlement'
        ]
    
    def get_day_of_week_display(self, obj):
        """Get display value for day of week"""
        if obj.day_of_week is None:
            return None
            
        days = [
            _('Monday'), _('Tuesday'), _('Wednesday'), _('Thursday'),
            _('Friday'), _('Saturday'), _('Sunday')
        ]
        return days[obj.day_of_week]


class SettlementScheduleCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a settlement schedule"""
    
    bank_account_id = serializers.CharField(write_only=True)
    amount_threshold = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False,
        allow_null=True
    )
    minimum_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        default=0
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
            'bank_account_id', 'schedule_type', 'is_active',
            'amount_threshold', 'minimum_amount', 'maximum_amount',
            'day_of_week', 'day_of_month', 'time_of_day'
        ]
    
    def validate_bank_account_id(self, value):
        """Validate bank account exists and is active"""
        try:
            bank_account = BankAccount.objects.get(id=value)
            if not bank_account.is_active:
                raise serializers.ValidationError(_("Bank account is inactive"))
            if not bank_account.is_verified:
                raise serializers.ValidationError(_("Bank account is not verified"))
            if not bank_account.paystack_recipient_code:
                raise serializers.ValidationError(_("Bank account does not have a recipient code"))
            return value
        except BankAccount.DoesNotExist:
            raise serializers.ValidationError(_("Bank account not found"))
    
    def validate(self, data):
        """Validate schedule parameters"""
        schedule_type = data.get('schedule_type')
        
        if schedule_type == 'weekly' and 'day_of_week' not in data:
            raise serializers.ValidationError({
                'day_of_week': _("Day of week is required for weekly schedules")
            })
            
        if schedule_type == 'monthly' and 'day_of_month' not in data:
            raise serializers.ValidationError({
                'day_of_month': _("Day of month is required for monthly schedules")
            })
            
        if schedule_type == 'threshold' and 'amount_threshold' not in data:
            raise serializers.ValidationError({
                'amount_threshold': _("Amount threshold is required for threshold schedules")
            })
            
        if 'minimum_amount' in data and 'maximum_amount' in data and data['maximum_amount']:
            if data['minimum_amount'] > data['maximum_amount']:
                raise serializers.ValidationError({
                    'minimum_amount': _("Minimum amount cannot be greater than maximum amount")
                })
                
        return data