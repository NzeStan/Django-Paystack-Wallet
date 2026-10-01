"""Money helpers: rounding, conversion to/from Paystack's minor units (kobo, pesewas, cents)."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from djmoney.money import Money

from wallet.conf import wallet_settings
from wallet.exceptions import InvalidAmount

TWO_PLACES = Decimal('0.01')
ZERO = Decimal('0.00')


def to_decimal(value):
    """Convert int/float/str/Decimal/Money to a Decimal rounded to 2 places."""
    if isinstance(value, Money):
        value = value.amount
    if value is None:
        raise InvalidAmount(message="Amount is required")
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidAmount(value) from exc


def quantize(value):
    """Round a Decimal to 2 places using banker-safe HALF_UP rounding."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_money(value, currency=None):
    """Return a Money instance in ``currency`` (defaults to WALLET_CURRENCY)."""
    if isinstance(value, Money):
        return Money(quantize(value.amount), value.currency)
    return Money(to_decimal(value), currency or wallet_settings.CURRENCY)


def to_minor_units(value):
    """Convert a major-unit amount (e.g. NGN 10.50) to Paystack minor units (1050)."""
    return int((to_decimal(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def from_minor_units(value):
    """Convert Paystack minor units (1050) to a major-unit Decimal (10.50)."""
    if value in (None, ''):
        return ZERO
    return quantize(Decimal(str(value)) / 100)


def money_to_dict(money):
    """Serialisable representation of a Money value."""
    if money is None:
        return None
    return {'amount': str(quantize(money.amount)), 'currency': str(money.currency)}
