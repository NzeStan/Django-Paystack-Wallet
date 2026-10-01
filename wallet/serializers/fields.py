"""Shared serializer fields and validators."""
from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from wallet.conf import wallet_settings
from wallet.constants import FEE_BEARERS


class MoneyAmountField(serializers.Field):
    """Read-only: renders a djmoney ``Money`` as a decimal string (currency is exposed separately)."""

    def __init__(self, **kwargs):
        kwargs['read_only'] = True
        super().__init__(**kwargs)

    def to_representation(self, value):
        if value is None:
            return None
        return str(getattr(value, 'amount', value))


class MoneyDecimalField(serializers.DecimalField):
    """Writable decimal amount that also renders djmoney ``Money`` values."""

    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 19)
        kwargs.setdefault('decimal_places', 2)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return super().to_representation(getattr(value, 'amount', value))


def amount_field(**kwargs):
    kwargs.setdefault('max_digits', 19)
    kwargs.setdefault('decimal_places', 2)
    kwargs.setdefault('min_value', Decimal('0.01'))
    return serializers.DecimalField(**kwargs)


class FeeBearerField(serializers.ChoiceField):
    """
    Lets API clients pick who bears the fee only when
    ``WALLET_ALLOW_FEE_BEARER_OVERRIDE`` is on (staff can always choose).
    """

    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('allow_null', True)
        super().__init__(choices=FEE_BEARERS, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        request = self.context.get('request')
        is_staff = bool(request and getattr(request.user, 'is_staff', False))
        if value and not (wallet_settings.ALLOW_FEE_BEARER_OVERRIDE or is_staff):
            raise serializers.ValidationError(_("Choosing the fee bearer is not allowed"))
        return value


class PinField(serializers.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('write_only', True)
        kwargs.setdefault('allow_blank', False)
        kwargs.setdefault('trim_whitespace', True)
        kwargs.setdefault('max_length', 12)
        super().__init__(**kwargs)


def validate_pin_format(value):
    length = int(wallet_settings.PIN_LENGTH)
    if not value.isdigit() or len(value) != length:
        raise serializers.ValidationError(_("PIN must be {length} digits").format(length=length))
    if len(set(value)) == 1 or value in '0123456789' or value in '9876543210':
        raise serializers.ValidationError(_("PIN is too easy to guess"))
    return value


class MetadataField(serializers.DictField):
    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('default', dict)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if len(str(value)) > 5000:
            raise serializers.ValidationError(_("Metadata is too large"))
        return value
