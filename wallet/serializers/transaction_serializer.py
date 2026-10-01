from decimal import Decimal

from rest_framework import serializers

from wallet.models import Transaction
from wallet.serializers.fields import MoneyAmountField


class TransactionSerializer(serializers.ModelSerializer):
    amount = MoneyAmountField()
    fees = MoneyAmountField()
    total_amount = MoneyAmountField()
    balance_after = MoneyAmountField()
    currency = serializers.SerializerMethodField()
    counterparty = serializers.SerializerMethodField()
    bank_account = serializers.SerializerMethodField()
    requires_otp = serializers.BooleanField(read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id', 'reference', 'transaction_type', 'transaction_type_display', 'direction', 'status',
            'status_display', 'amount', 'fees', 'total_amount', 'balance_after', 'ledger_sequence', 'currency',
            'fee_bearer',
            'payment_method', 'channel', 'description', 'counterparty', 'bank_account', 'card',
            'related_transaction', 'requires_otp', 'failed_reason', 'created_at', 'completed_at',
        ]
        read_only_fields = fields

    def get_currency(self, obj):
        return str(obj.amount.currency)

    def get_counterparty(self, obj):
        wallet = obj.counterparty_wallet
        if wallet is None:
            return None
        return {'wallet_id': str(wallet.pk), 'tag': wallet.tag}

    def get_bank_account(self, obj):
        account = obj.recipient_bank_account
        if account is None:
            return None
        return {
            'id': str(account.pk), 'bank_name': account.bank.name, 'account_name': account.account_name,
            'account_number': account.masked_account_number,
        }


# Aliases kept for existing imports
TransactionListSerializer = TransactionSerializer


class TransactionDetailSerializer(TransactionSerializer):
    metadata = serializers.JSONField(read_only=True)
    paystack_reference = serializers.CharField(read_only=True)
    paystack_transfer_code = serializers.CharField(read_only=True)

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + ['metadata', 'paystack_reference', 'paystack_transfer_code']
        read_only_fields = fields


class VerifyTransactionSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=100)


class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=19, decimal_places=2, required=False, min_value=Decimal('0.01'))
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
