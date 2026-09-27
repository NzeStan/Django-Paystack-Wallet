"""
Model fields.

``WalletMoneyField`` behaves exactly like django-money's ``MoneyField`` but its
currency default comes from ``WALLET_CURRENCY`` at runtime while migrations
always serialise a fixed value. Without this, changing ``WALLET_CURRENCY`` in a
project would make ``makemigrations`` generate migrations inside this package.
"""
from djmoney.models.fields import CurrencyField, MoneyField
from djmoney.money import Money

from wallet.constants import SUPPORTED_CURRENCIES

# Value written into migrations. Never change it.
MIGRATION_CURRENCY = 'NGN'


def default_currency():
    from wallet.conf import wallet_settings
    return wallet_settings.CURRENCY


class WalletCurrencyField(CurrencyField):
    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        kwargs['default'] = MIGRATION_CURRENCY
        kwargs.pop('price_field', None)
        return name, 'wallet.models.fields.WalletCurrencyField', args, kwargs

    def get_default(self):
        return default_currency()


class WalletMoneyField(MoneyField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 19)
        kwargs.setdefault('decimal_places', 2)
        kwargs.setdefault('default_currency', MIGRATION_CURRENCY)
        kwargs.setdefault('currency_choices', SUPPORTED_CURRENCIES)
        super().__init__(*args, **kwargs)

    def add_currency_field(self, cls, name):
        from djmoney.models.fields import get_currency_field_name

        currency_field = WalletCurrencyField(
            price_field=self,
            max_length=self.currency_max_length,
            default=self.default_currency,
            editable=False,
            choices=self.currency_choices,
            null=self.null,
        )
        currency_field.creation_counter = self.creation_counter - 1
        cls.add_to_class(get_currency_field_name(name, self), currency_field)
        self._currency_field = currency_field

    def get_default(self):
        default = super().get_default()
        if isinstance(default, Money):
            return Money(default.amount, default_currency())
        return default

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        kwargs['default_currency'] = MIGRATION_CURRENCY
        if isinstance(kwargs.get('default'), Money):
            kwargs['default'] = kwargs['default'].amount
        kwargs.pop('currency_choices', None)
        return name, 'wallet.models.fields.WalletMoneyField', args, kwargs
