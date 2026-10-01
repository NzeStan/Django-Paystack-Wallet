from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from wallet.constants import PAYSTACK_CHANNELS, RECIPIENT_LOOKUP_TYPES
from wallet.models import Wallet
from wallet.serializers.fields import (
    FeeBearerField,
    MetadataField,
    MoneyAmountField,
    PinField,
    amount_field,
    validate_pin_format,
)


class WalletSerializer(serializers.ModelSerializer):
    balance = MoneyAmountField()
    currency = serializers.CharField(read_only=True)
    has_pin = serializers.BooleanField(read_only=True)
    is_operational = serializers.BooleanField(read_only=True)
    dedicated_account = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id', 'tag', 'phone_number', 'balance', 'currency', 'is_active', 'is_locked', 'is_operational',
            'has_pin', 'dedicated_account', 'last_transaction_date', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_dedicated_account(self, obj):
        if not obj.dedicated_account_number:
            return None
        return {
            'account_number': obj.dedicated_account_number,
            'account_name': obj.dedicated_account_name,
            'bank_name': obj.dedicated_account_bank,
            'active': obj.dedicated_account_active,
        }


class WalletDetailSerializer(WalletSerializer):
    daily_limit = serializers.SerializerMethodField()
    daily_spent = serializers.SerializerMethodField()

    class Meta(WalletSerializer.Meta):
        fields = WalletSerializer.Meta.fields + ['daily_limit', 'daily_spent', 'customer_identified']
        read_only_fields = fields

    def get_daily_limit(self, obj):
        limit = obj.get_daily_limit()
        return str(limit) if limit is not None else None

    def get_daily_spent(self, obj):
        from wallet.utils.money import quantize
        return str(quantize(obj.get_daily_outgoing_total()))


class WalletUpdateSerializer(serializers.Serializer):
    tag = serializers.CharField(required=False, max_length=30)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20)


# Backwards compatible alias
WalletCreateUpdateSerializer = WalletUpdateSerializer


class DepositSerializer(serializers.Serializer):
    amount = amount_field()
    email = serializers.EmailField(required=False)
    callback_url = serializers.URLField(required=False)
    reference = serializers.CharField(required=False, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=PAYSTACK_CHANNELS), required=False, allow_empty=False,
    )
    metadata = MetadataField()
    fee_bearer = FeeBearerField()


WalletDepositSerializer = DepositSerializer


class VerifyDepositSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=100)


class ChargeCardSerializer(serializers.Serializer):
    card_id = serializers.UUIDField(required=False, help_text=_('Defaults to the wallet default card'))
    amount = amount_field()
    reference = serializers.CharField(required=False, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    metadata = MetadataField()
    fee_bearer = FeeBearerField()
    pin = PinField()


class WithdrawSerializer(serializers.Serializer):
    amount = amount_field()
    bank_account_id = serializers.UUIDField(required=False, help_text=_('Defaults to the default bank account'))
    description = serializers.CharField(required=False, allow_blank=True, max_length=100)
    reference = serializers.CharField(required=False, max_length=50)
    metadata = MetadataField()
    fee_bearer = FeeBearerField()
    pin = PinField()


WalletWithdrawSerializer = WithdrawSerializer


class FinalizeWithdrawalSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=10)
    transaction_id = serializers.UUIDField(required=False)
    reference = serializers.CharField(required=False, max_length=100)
    transfer_code = serializers.CharField(required=False, max_length=100)

    def validate(self, attrs):
        if not any(attrs.get(key) for key in ('transaction_id', 'reference', 'transfer_code')):
            raise serializers.ValidationError(_("Provide transaction_id, reference or transfer_code"))
        return attrs


class ResendOtpSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField(required=False)
    reference = serializers.CharField(required=False, max_length=100)
    transfer_code = serializers.CharField(required=False, max_length=100)

    def validate(self, attrs):
        if not any(attrs.get(key) for key in ('transaction_id', 'reference', 'transfer_code')):
            raise serializers.ValidationError(_("Provide transaction_id, reference or transfer_code"))
        return attrs


class TransferSerializer(serializers.Serializer):
    amount = amount_field()
    recipient = serializers.CharField(
        required=False, max_length=255,
        help_text=_('Wallet ID, tag, phone number or email of the recipient'),
    )
    recipient_type = serializers.ChoiceField(choices=RECIPIENT_LOOKUP_TYPES + (('phone', 'Phone'),), required=False)
    destination_wallet_id = serializers.UUIDField(required=False)
    phone_number = serializers.CharField(required=False, max_length=20)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    reference = serializers.CharField(required=False, max_length=100)
    metadata = MetadataField()
    fee_bearer = FeeBearerField()
    pin = PinField()

    def validate(self, attrs):
        if attrs.get('destination_wallet_id'):
            attrs['recipient'], attrs['recipient_type'] = str(attrs['destination_wallet_id']), 'id'
        elif attrs.get('phone_number'):
            attrs['recipient'], attrs['recipient_type'] = attrs['phone_number'], 'phone_number'
        if not attrs.get('recipient'):
            raise serializers.ValidationError({'recipient': _("This field is required")})
        return attrs


WalletTransferSerializer = TransferSerializer


class PaySerializer(serializers.Serializer):
    amount = amount_field()
    merchant = serializers.CharField(required=False, max_length=255,
                                     help_text=_('Wallet ID, tag, phone or email of the seller (optional)'))
    escrow = serializers.BooleanField(default=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    reference = serializers.CharField(required=False, max_length=100)
    metadata = MetadataField()
    fee_bearer = FeeBearerField()
    pin = PinField()


class RecipientLookupSerializer(serializers.Serializer):
    recipient = serializers.CharField(max_length=255)
    recipient_type = serializers.ChoiceField(choices=RECIPIENT_LOOKUP_TYPES + (('phone', 'Phone'),), required=False)


class SetPinSerializer(serializers.Serializer):
    pin = serializers.CharField(write_only=True, max_length=12, validators=[validate_pin_format])
    confirm_pin = serializers.CharField(write_only=True, max_length=12)
    current_pin = serializers.CharField(write_only=True, max_length=12, required=False)

    def validate(self, attrs):
        if attrs['pin'] != attrs['confirm_pin']:
            raise serializers.ValidationError({'confirm_pin': _("PINs do not match")})
        return attrs


class DedicatedAccountSerializer(serializers.Serializer):
    preferred_bank = serializers.CharField(required=False, max_length=50)


class CustomerValidationSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False)
    identification_type = serializers.ChoiceField(choices=(('bank_account', 'Bank account'), ('bvn', 'BVN')),
                                                  default='bank_account')
    country = serializers.CharField(max_length=2, default='NG')
    bvn = serializers.CharField(max_length=11, required=False)
    bank_code = serializers.CharField(max_length=20, required=False)
    account_number = serializers.CharField(max_length=20, required=False)
