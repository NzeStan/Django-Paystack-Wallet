from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from decimal import Decimal

from wallet.models import Transaction, Wallet
from wallet.constants import TRANSACTION_TYPES, TRANSACTION_STATUSES, PAYMENT_METHODS


# ==========================================
# BASE & FULL SERIALIZERS
# ==========================================

class TransactionSerializer(serializers.ModelSerializer):
    """
    Full serializer for the Transaction model
    
    Provides complete transaction data including all fields and relationships.
    Used for detailed transaction views and comprehensive data exports.
    """
    
    # Wallet fields
    wallet_id = serializers.UUIDField(source='wallet.id', read_only=True)
    wallet_tag = serializers.CharField(source='wallet.tag', read_only=True)
    wallet_user_email = serializers.EmailField(source='wallet.user.email', read_only=True)
    
    # Amount fields
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
    
    # Display fields
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    payment_method_display = serializers.CharField(
        source='get_payment_method_display',
        read_only=True
    )
    
    # Relationship fields
    recipient_wallet_id = serializers.UUIDField(
        source='recipient_wallet.id',
        read_only=True,
        allow_null=True
    )
    recipient_wallet_tag = serializers.CharField(
        source='recipient_wallet.tag',
        read_only=True,
        allow_null=True
    )
    recipient_bank_account_id = serializers.UUIDField(
        source='recipient_bank_account.id',
        read_only=True,
        allow_null=True
    )
    card_id = serializers.UUIDField(
        source='card.id',
        read_only=True,
        allow_null=True
    )
    related_transaction_id = serializers.UUIDField(
        source='related_transaction.id',
        read_only=True,
        allow_null=True
    )
    
    # Fees field
    fees_value = serializers.DecimalField(
        source='fees.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    
    # Computed fields
    net_amount = serializers.DecimalField(
        source='net_amount.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    is_successful = serializers.BooleanField(read_only=True)
    is_failed = serializers.BooleanField(read_only=True)
    is_pending = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'wallet_id', 'wallet_tag', 'wallet_user_email',
            'amount_value', 'amount_currency', 'reference',
            'transaction_type', 'transaction_type_display',
            'status', 'status_display',
            'payment_method', 'payment_method_display',
            'description', 'metadata',
            'recipient_wallet_id', 'recipient_wallet_tag',
            'recipient_bank_account_id', 'card_id', 'related_transaction_id',
            'fees_value', 'net_amount',
            'ip_address', 'user_agent',
            'is_successful', 'is_failed', 'is_pending',
            'created_at', 'updated_at', 'completed_at', 'failed_reason'
        ]
        read_only_fields = fields


class TransactionDetailSerializer(TransactionSerializer):
    """
    Detailed serializer for the Transaction model
    
    Extends TransactionSerializer with additional Paystack-specific fields.
    Used for single transaction detail views.
    """
    
    paystack_reference = serializers.CharField(read_only=True)
    paystack_response = serializers.JSONField(read_only=True)
    
    # Nested related objects for detail view
    recipient_wallet_details = serializers.SerializerMethodField()
    recipient_bank_account_details = serializers.SerializerMethodField()
    
    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + [
            'paystack_reference', 'paystack_response',
            'recipient_wallet_details', 'recipient_bank_account_details'
        ]
        read_only_fields = fields
    
    def get_recipient_wallet_details(self, obj):
        """Get recipient wallet basic details"""
        if obj.recipient_wallet:
            return {
                'id': str(obj.recipient_wallet.id),
                'tag': obj.recipient_wallet.tag,
                'user_email': obj.recipient_wallet.user.email if obj.recipient_wallet.user else None
            }
        return None
    
    def get_recipient_bank_account_details(self, obj):
        """Get recipient bank account basic details"""
        if obj.recipient_bank_account:
            return {
                'id': str(obj.recipient_bank_account.id),
                'account_name': obj.recipient_bank_account.account_name,
                'account_number': obj.recipient_bank_account.account_number,
                'bank_name': obj.recipient_bank_account.bank.name if obj.recipient_bank_account.bank else None
            }
        return None


# ==========================================
# LIST & LIGHTWEIGHT SERIALIZERS
# ==========================================

class TransactionListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing transactions
    
    Optimized for performance with minimal fields. Used for transaction lists,
    pagination, and scenarios where full detail is not required.
    """
    
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
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'reference', 'amount_value', 'amount_currency',
            'transaction_type', 'transaction_type_display',
            'status', 'status_display',
            'description', 'created_at', 'completed_at'
        ]
        read_only_fields = fields


class TransactionMinimalSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for transaction references
    
    Used when including transaction data in other serializers or
    when only basic transaction info is needed.
    """
    
    amount_value = serializers.DecimalField(
        source='amount.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    
    class Meta:
        model = Transaction
        fields = ['id', 'reference', 'amount_value', 'transaction_type', 'status']
        read_only_fields = fields


# ==========================================
# CREATE & UPDATE SERIALIZERS
# ==========================================

class TransactionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating transactions
    
    Used when manually creating transactions through the API.
    Includes validation for required fields and amount constraints.
    """
    
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01")
    )
    
    class Meta:
        model = Transaction
        fields = [
            'wallet', 'amount', 'transaction_type', 'description',
            'metadata', 'payment_method', 'recipient_wallet',
            'recipient_bank_account'
        ]
    
    def validate_amount(self, value):
        """Validate transaction amount"""
        if value <= 0:
            raise serializers.ValidationError(
                _("Transaction amount must be greater than zero")
            )
        
        # Check maximum transaction limit from settings
        from wallet.settings import get_wallet_setting
        max_amount = get_wallet_setting('MAXIMUM_DAILY_TRANSACTION')
        
        if value > max_amount:
            raise serializers.ValidationError(
                _("Transaction amount exceeds maximum limit of {max}").format(
                    max=max_amount
                )
            )
        
        return value
    
    def validate(self, data):
        """Cross-field validation"""
        transaction_type = data.get('transaction_type')
        
        # Validate transfer transactions
        from wallet.constants import TRANSACTION_TYPE_TRANSFER
        if transaction_type == TRANSACTION_TYPE_TRANSFER:
            if not data.get('recipient_wallet'):
                raise serializers.ValidationError({
                    'recipient_wallet': _("Recipient wallet is required for transfers")
                })
            
            # Prevent self-transfer
            if data.get('wallet') == data.get('recipient_wallet'):
                raise serializers.ValidationError({
                    'recipient_wallet': _("Cannot transfer to the same wallet")
                })
        
        # Validate withdrawal transactions
        from wallet.constants import TRANSACTION_TYPE_WITHDRAWAL
        if transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            if not data.get('recipient_bank_account'):
                raise serializers.ValidationError({
                    'recipient_bank_account': _(
                        "Bank account is required for withdrawals"
                    )
                })
        
        return data


# ==========================================
# ACTION SERIALIZERS
# ==========================================

class TransactionVerifySerializer(serializers.Serializer):
    """
    Serializer for verifying transactions
    
    Used to verify a transaction by its reference number,
    typically after a payment gateway callback.
    """
    
    reference = serializers.CharField(
        max_length=100,
        required=True,
        help_text=_("Transaction reference to verify")
    )
    
    def validate_reference(self, value):
        """Validate that the reference exists"""
        try:
            Transaction.objects.get(reference=value)
        except Transaction.DoesNotExist:
            raise serializers.ValidationError(
                _("Transaction with reference '{ref}' not found").format(ref=value)
            )
        return value


class TransactionRefundSerializer(serializers.Serializer):
    """
    Serializer for refunding transactions
    
    Used to initiate a refund for a completed transaction.
    Supports partial refunds.
    """
    
    transaction_id = serializers.UUIDField(
        required=True,
        help_text=_("ID of the transaction to refund")
    )
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0.01"),
        required=False,
        help_text=_("Amount to refund (leave empty for full refund)")
    )
    reason = serializers.CharField(
        max_length=500,
        required=False,
        help_text=_("Reason for the refund")
    )
    
    def validate_transaction_id(self, value):
        """Validate that the transaction exists and can be refunded"""
        try:
            transaction = Transaction.objects.get(id=value)
            
            if not transaction.can_be_refunded():
                raise serializers.ValidationError(
                    _("This transaction cannot be refunded")
                )
            
        except Transaction.DoesNotExist:
            raise serializers.ValidationError(
                _("Transaction not found")
            )
        
        return value
    
    def validate(self, data):
        """Validate refund amount against original transaction"""
        if 'amount' in data:
            transaction = Transaction.objects.get(id=data['transaction_id'])
            
            if data['amount'] > transaction.amount.amount:
                raise serializers.ValidationError({
                    'amount': _(
                        "Refund amount cannot exceed original transaction amount"
                    )
                })
        
        return data


class TransactionCancelSerializer(serializers.Serializer):
    """
    Serializer for cancelling transactions
    
    Used to cancel a pending transaction.
    """
    
    transaction_id = serializers.UUIDField(
        required=True,
        help_text=_("ID of the transaction to cancel")
    )
    reason = serializers.CharField(
        max_length=500,
        required=False,
        help_text=_("Reason for cancellation")
    )
    
    def validate_transaction_id(self, value):
        """Validate that the transaction exists and can be cancelled"""
        try:
            transaction = Transaction.objects.get(id=value)
            
            if not transaction.can_be_cancelled():
                raise serializers.ValidationError(
                    _("Only pending transactions can be cancelled")
                )
            
        except Transaction.DoesNotExist:
            raise serializers.ValidationError(
                _("Transaction not found")
            )
        
        return value


# ==========================================
# FILTER SERIALIZERS
# ==========================================

class TransactionFilterSerializer(serializers.Serializer):
    """
    Serializer for transaction filtering parameters
    
    Used to validate and parse query parameters for filtering
    transaction lists.
    """
    
    wallet_id = serializers.UUIDField(
        required=False,
        help_text=_("Filter by wallet ID")
    )
    transaction_type = serializers.ChoiceField(
        choices=TRANSACTION_TYPES,
        required=False,
        help_text=_("Filter by transaction type")
    )
    status = serializers.ChoiceField(
        choices=TRANSACTION_STATUSES,
        required=False,
        help_text=_("Filter by status")
    )
    payment_method = serializers.ChoiceField(
        choices=PAYMENT_METHODS,
        required=False,
        help_text=_("Filter by payment method")
    )
    reference = serializers.CharField(
        max_length=100,
        required=False,
        help_text=_("Filter by reference")
    )
    start_date = serializers.DateTimeField(
        required=False,
        help_text=_("Filter by start date (ISO 8601 format)")
    )
    end_date = serializers.DateTimeField(
        required=False,
        help_text=_("Filter by end date (ISO 8601 format)")
    )
    min_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0"),
        required=False,
        help_text=_("Filter by minimum amount")
    )
    max_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        min_value=Decimal("0"),
        required=False,
        help_text=_("Filter by maximum amount")
    )
    limit = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=20,
        required=False,
        help_text=_("Number of results per page")
    )
    offset = serializers.IntegerField(
        min_value=0,
        default=0,
        required=False,
        help_text=_("Offset for pagination")
    )
    
    def validate(self, data):
        """Cross-field validation for date ranges and amounts"""
        # Validate date range
        if 'start_date' in data and 'end_date' in data:
            if data['start_date'] > data['end_date']:
                raise serializers.ValidationError({
                    'end_date': _("End date must be after start date")
                })
        
        # Validate amount range
        if 'min_amount' in data and 'max_amount' in data:
            if data['min_amount'] > data['max_amount']:
                raise serializers.ValidationError({
                    'max_amount': _("Maximum amount must be greater than minimum amount")
                })
        
        return data


# ==========================================
# STATISTICS & ANALYTICS SERIALIZERS
# ==========================================

class TransactionStatisticsSerializer(serializers.Serializer):
    """
    Serializer for transaction statistics
    
    Used to format transaction statistics data including counts,
    totals, and averages.
    """
    
    total_count = serializers.IntegerField(read_only=True)
    successful_count = serializers.IntegerField(read_only=True)
    pending_count = serializers.IntegerField(read_only=True)
    failed_count = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    average_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    total_fees = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    by_type = serializers.DictField(read_only=True)


class TransactionSummarySerializer(serializers.Serializer):
    """
    Serializer for transaction summary data
    
    Provides a comprehensive summary of transactions grouped
    by type and status.
    """
    
    by_type = serializers.DictField(read_only=True)
    by_status = serializers.DictField(read_only=True)
    overview = serializers.DictField(read_only=True)


# ==========================================
# EXPORT SERIALIZERS
# ==========================================

class TransactionExportSerializer(serializers.ModelSerializer):
    """
    Serializer for exporting transactions
    
    Formats transaction data for CSV/Excel exports with
    flattened fields for easy spreadsheet viewing.
    """
    
    wallet_tag = serializers.CharField(source='wallet.tag', read_only=True)
    wallet_user_email = serializers.EmailField(source='wallet.user.email', read_only=True)
    amount = serializers.DecimalField(
        source='amount.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    currency = serializers.CharField(source='amount.currency.code', read_only=True)
    transaction_type_name = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True
    )
    status_name = serializers.CharField(source='get_status_display', read_only=True)
    fees = serializers.DecimalField(
        source='fees.amount',
        decimal_places=2,
        max_digits=19,
        read_only=True
    )
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'reference', 'wallet_tag', 'wallet_user_email',
            'amount', 'currency', 'fees',
            'transaction_type', 'transaction_type_name',
            'status', 'status_name',
            'description', 'created_at', 'completed_at', 'failed_reason'
        ]
        read_only_fields = fields

#admin only bulk operations serializers
class BulkTransactionCreateSerializer(serializers.Serializer):
    """Serializer for bulk transaction creation (admin-only)"""
    
    transactions = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=100  # Reasonable limit
    )    

class BulkTransactionUpdateSerializer(serializers.Serializer):
    """Serializer for bulk transaction status update (admin-only)"""
    
    transaction_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100
    )
    status = serializers.ChoiceField(choices=TRANSACTION_STATUSES)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)