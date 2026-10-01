from rest_framework import serializers

from wallet.constants import (
    PAYMENT_CHANNELS,
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_TYPE_WITHDRAWAL,
)
from wallet.serializers.fields import FeeBearerField, amount_field

QUOTABLE_TYPES = (
    (TRANSACTION_TYPE_DEPOSIT, 'Deposit'),
    (TRANSACTION_TYPE_WITHDRAWAL, 'Withdrawal'),
    (TRANSACTION_TYPE_TRANSFER, 'Transfer'),
    (TRANSACTION_TYPE_PAYMENT, 'Payment'),
)


class FeeQuoteSerializer(serializers.Serializer):
    amount = amount_field()
    transaction_type = serializers.ChoiceField(choices=QUOTABLE_TYPES)
    payment_channel = serializers.ChoiceField(choices=PAYMENT_CHANNELS, required=False)
    fee_bearer = FeeBearerField()
