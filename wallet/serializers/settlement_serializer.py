from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from djmoney.money import Money
from rest_framework import serializers

from wallet.models import BankAccount, Settlement, SettlementSchedule
from wallet.serializers.bank_account_serializer import BankAccountSerializer
from wallet.serializers.fields import MoneyAmountField, MoneyDecimalField, PinField, amount_field


class SettlementSerializer(serializers.ModelSerializer):
    amount = MoneyAmountField()
    fees = MoneyAmountField()
    currency = serializers.SerializerMethodField()
    bank_account = BankAccountSerializer(read_only=True)
    requires_otp = serializers.BooleanField(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Settlement
        fields = [
            'id', 'reference', 'amount', 'fees', 'currency', 'status', 'status_display', 'bank_account', 'reason',
            'transaction', 'requires_otp', 'failure_reason', 'settled_at', 'created_at',
        ]
        read_only_fields = fields

    def get_currency(self, obj):
        return str(obj.amount.currency)


SettlementDetailSerializer = SettlementSerializer


class SettlementCreateSerializer(serializers.Serializer):
    amount = amount_field()
    bank_account_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=100)
    pin = PinField()


class OtpSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=10)


class SettlementScheduleSerializer(serializers.ModelSerializer):
    bank_account_id = serializers.UUIDField(write_only=True)
    bank_account = BankAccountSerializer(read_only=True)
    amount_threshold = MoneyDecimalField(required=False, allow_null=True)
    minimum_amount = MoneyDecimalField(required=False)
    maximum_amount = MoneyDecimalField(required=False, allow_null=True)

    class Meta:
        model = SettlementSchedule
        fields = [
            'id', 'bank_account_id', 'bank_account', 'schedule_type', 'is_active', 'amount_threshold',
            'minimum_amount', 'maximum_amount', 'day_of_week', 'day_of_month', 'time_of_day', 'last_settlement',
            'next_settlement', 'created_at',
        ]
        read_only_fields = ['id', 'bank_account', 'last_settlement', 'next_settlement', 'created_at']

    def validate_bank_account_id(self, value):
        wallet = self.context['wallet']
        account = BankAccount.objects.filter(pk=value, wallet=wallet, is_active=True).first()
        if account is None:
            raise serializers.ValidationError(_("Bank account not found"))
        return account

    def validate(self, attrs):
        wallet = self.context['wallet']
        for field in ('amount_threshold', 'minimum_amount', 'maximum_amount'):
            if field in attrs and attrs[field] is not None:
                attrs[field] = Money(Decimal(attrs[field]), wallet.currency)
        instance = self.instance or SettlementSchedule(wallet=wallet)
        probe = SettlementSchedule(**{
            **{f: getattr(instance, f) for f in ('schedule_type', 'amount_threshold', 'day_of_week',
                                                 'day_of_month')},
            **{k: v for k, v in attrs.items() if k in ('schedule_type', 'amount_threshold', 'day_of_week',
                                                       'day_of_month')},
        })
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            probe.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs

    def create(self, validated_data):
        validated_data['bank_account'] = validated_data.pop('bank_account_id')
        return SettlementSchedule.objects.create(wallet=self.context['wallet'], **validated_data)

    def update(self, instance, validated_data):
        if 'bank_account_id' in validated_data:
            validated_data['bank_account'] = validated_data.pop('bank_account_id')
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.next_settlement = instance.compute_next_settlement() if instance.is_active else None
        instance.save()
        return instance
