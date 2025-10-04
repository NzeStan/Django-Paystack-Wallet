# from rest_framework import serializers
# from django.utils.translation import gettext_lazy as _

# from wallet.models import Transaction


# class TransactionSerializer(serializers.ModelSerializer):
#     """Serializer for the Transaction model"""
    
#     wallet_id = serializers.CharField(source='wallet.id', read_only=True)
#     amount_value = serializers.DecimalField(
#         source='amount.amount', 
#         decimal_places=2, 
#         max_digits=19, 
#         read_only=True
#     )
#     amount_currency = serializers.CharField(
#         source='amount.currency.code', 
#         read_only=True
#     )
#     transaction_type_display = serializers.CharField(
#         source='get_transaction_type_display', 
#         read_only=True
#     )
#     status_display = serializers.CharField(
#         source='get_status_display', 
#         read_only=True
#     )
#     payment_method_display = serializers.CharField(
#         source='get_payment_method_display', 
#         read_only=True
#     )
#     recipient_wallet_id = serializers.CharField(
#         source='recipient_wallet.id', 
#         read_only=True
#     )
#     recipient_bank_account_id = serializers.CharField(
#         source='recipient_bank_account.id', 
#         read_only=True
#     )
#     card_id = serializers.CharField(
#         source='card.id', 
#         read_only=True
#     )
#     related_transaction_id = serializers.CharField(
#         source='related_transaction.id', 
#         read_only=True
#     )
#     fees_value = serializers.DecimalField(
#         source='fees.amount', 
#         decimal_places=2, 
#         max_digits=19, 
#         read_only=True
#     )
    
#     class Meta:
#         model = Transaction
#         fields = [
#             'id', 'wallet_id', 'amount_value', 'amount_currency', 'reference',
#             'transaction_type', 'transaction_type_display', 'status', 'status_display',
#             'payment_method', 'payment_method_display', 'description', 'metadata',
#             'recipient_wallet_id', 'recipient_bank_account_id', 'card_id',
#             'related_transaction_id', 'fees_value', 'ip_address', 'user_agent',
#             'created_at', 'updated_at', 'completed_at', 'failed_reason'
#         ]
#         read_only_fields = fields


# class TransactionDetailSerializer(TransactionSerializer):
#     """Detailed serializer for the Transaction model"""
    
#     paystack_reference = serializers.CharField(read_only=True)
#     paystack_response = serializers.JSONField(read_only=True)
    
#     class Meta(TransactionSerializer.Meta):
#         fields = TransactionSerializer.Meta.fields + ['paystack_reference', 'paystack_response']
#         read_only_fields = fields


# class TransactionListSerializer(serializers.ModelSerializer):
#     """Lightweight serializer for listing transactions"""
    
#     amount_value = serializers.DecimalField(
#         source='amount.amount', 
#         decimal_places=2, 
#         max_digits=19, 
#         read_only=True
#     )
#     amount_currency = serializers.CharField(
#         source='amount.currency.code', 
#         read_only=True
#     )
#     transaction_type_display = serializers.CharField(
#         source='get_transaction_type_display', 
#         read_only=True
#     )
#     status_display = serializers.CharField(
#         source='get_status_display', 
#         read_only=True
#     )
    
#     class Meta:
#         model = Transaction
#         fields = [
#             'id', 'reference', 'amount_value', 'amount_currency',
#             'transaction_type', 'transaction_type_display', 'status', 'status_display',
#             'description', 'created_at', 'completed_at'
#         ]
#         read_only_fields = fields


# class TransactionFilterSerializer(serializers.Serializer):
#     """Serializer for transaction filtering parameters"""
    
#     wallet_id = serializers.CharField(required=False)
#     transaction_type = serializers.CharField(required=False)
#     status = serializers.CharField(required=False)
#     reference = serializers.CharField(required=False)
#     start_date = serializers.DateTimeField(required=False)
#     end_date = serializers.DateTimeField(required=False)
#     min_amount = serializers.DecimalField(
#         decimal_places=2,
#         max_digits=19,
#         required=False
#     )
#     max_amount = serializers.DecimalField(
#         decimal_places=2,
#         max_digits=19,
#         required=False
#     )
#     payment_method = serializers.CharField(required=False)
#     limit = serializers.IntegerField(
#         min_value=1,
#         max_value=100,
#         default=20,
#         required=False
#     )
#     offset = serializers.IntegerField(
#         min_value=0,
#         default=0,
#         required=False
#     )


# class TransactionVerifySerializer(serializers.Serializer):
#     """Serializer for verifying transactions"""
    
#     reference = serializers.CharField()


# class TransactionRefundSerializer(serializers.Serializer):
#     """Serializer for refunding transactions"""
    
#     transaction_id = serializers.CharField()
#     amount = serializers.DecimalField(
#         decimal_places=2,
#         max_digits=19,
#         required=False
#     )
#     reason = serializers.CharField(required=False)

#     def validate(self, data):
#         # NOTE: Do NOT fetch the transaction here. Let the view handle it.
#         return data

from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from wallet.models import Transaction, Wallet


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for the Transaction model"""
    
    wallet_id = serializers.CharField(source='wallet.id', read_only=True)
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
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', 
        read_only=True
    )
    recipient_wallet_id = serializers.CharField(
        source='recipient_wallet.id', 
        read_only=True
    )
    recipient_bank_account_id = serializers.CharField(
        source='recipient_bank_account.id', 
        read_only=True
    )
    card_id = serializers.CharField(
        source='card.id', 
        read_only=True
    )
    related_transaction_id = serializers.CharField(
        source='related_transaction.id', 
        read_only=True
    )
    fees_value = serializers.DecimalField(
        source='fees.amount', 
        decimal_places=2, 
        max_digits=19, 
        read_only=True
    )
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'wallet_id', 'amount_value', 'amount_currency', 'reference',
            'transaction_type', 'transaction_type_display', 'status', 'status_display',
            'payment_method', 'payment_method_display', 'description', 'metadata',
            'recipient_wallet_id', 'recipient_bank_account_id', 'card_id',
            'related_transaction_id', 'fees_value', 'ip_address', 'user_agent',
            'created_at', 'updated_at', 'completed_at', 'failed_reason'
        ]
        read_only_fields = fields


class TransactionDetailSerializer(TransactionSerializer):
    """Detailed serializer for the Transaction model"""
    
    paystack_reference = serializers.CharField(read_only=True)
    paystack_response = serializers.JSONField(read_only=True)
    
    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + ['paystack_reference', 'paystack_response']
        read_only_fields = fields


class TransactionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing transactions"""
    
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
            'transaction_type', 'transaction_type_display', 'status', 'status_display',
            'description', 'created_at', 'completed_at'
        ]
        read_only_fields = fields


class TransactionFilterSerializer(serializers.Serializer):
    """Serializer for transaction filtering parameters"""
    
    wallet_id = serializers.CharField(required=False)
    transaction_type = serializers.CharField(required=False)
    status = serializers.CharField(required=False)
    reference = serializers.CharField(required=False)
    start_date = serializers.DateTimeField(required=False)
    end_date = serializers.DateTimeField(required=False)
    min_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False
    )
    max_amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False
    )
    payment_method = serializers.CharField(required=False)
    limit = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=20,
        required=False
    )
    offset = serializers.IntegerField(
        min_value=0,
        default=0,
        required=False
    )


class TransactionVerifySerializer(serializers.Serializer):
    """Serializer for verifying transactions"""
    
    reference = serializers.CharField()


class TransactionRefundSerializer(serializers.Serializer):
    """Serializer for refunding transactions"""
    
    transaction_id = serializers.CharField()
    amount = serializers.DecimalField(
        decimal_places=2,
        max_digits=19,
        required=False
    )
    reason = serializers.CharField(required=False)
    
    def validate(self, data):
        """Validate refund data"""
        from wallet.models import Transaction
        
        # Check if transaction exists
        try:
            transaction = Transaction.objects.get(id=data['transaction_id'])
        except Transaction.DoesNotExist:
            raise serializers.ValidationError({
                'transaction_id': _("Transaction not found")
            })
            
        # Check if transaction can be refunded
        if transaction.status != 'success':
            raise serializers.ValidationError({
                'transaction_id': _("Only successful transactions can be refunded")
            })
            
        # Check if transaction type can be refunded
        if transaction.transaction_type not in ['payment', 'deposit']:
            raise serializers.ValidationError({
                'transaction_id': _("Only payment and deposit transactions can be refunded")
            })
            
        # Validate refund amount
        if 'amount' in data and data['amount']:
            if data['amount'] > transaction.amount.amount:
                raise serializers.ValidationError({
                    'amount': _("Refund amount cannot exceed original transaction amount")
                })
                
        return data