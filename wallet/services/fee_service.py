"""
Fee calculation.

Fees are part of the core because every money movement must know exactly how
much leaves the payer and how much reaches the receiver. *Pricing* is
pluggable:

* settings-based pricing (defaults mirror Paystack Nigeria's published rates)
* database pricing via :class:`~wallet.models.FeeConfiguration`
  (``WALLET_USE_DATABASE_FEE_CONFIG = True``), per wallet or global
* your own calculator: subclass :class:`FeeCalculator`, override
  :meth:`FeeCalculator.get_fee` (and/or :meth:`get_default_bearer`) and point
  ``WALLET_FEE_CALCULATOR`` at it

Bearer semantics are the same for every operation:

============  ===========================================================
customer      the payer pays the fee on top of the amount
merchant      the receiver absorbs the fee (it is deducted from what they get)
platform      the platform absorbs the fee; nobody is charged
split         shared between payer and receiver (WALLET_FEE_SPLIT_*)
============  ===========================================================

For each operation the "payer" and "receiver" are:

* deposit    - card/bank payer -> the wallet
* withdrawal - the wallet -> the bank account
* transfer   - the sending wallet -> the receiving wallet
* payment    - the buyer's wallet -> the merchant (wallet or platform)
"""
import logging
from decimal import Decimal

from djmoney.money import Money

from wallet.conf import wallet_settings
from wallet.constants import (
    FEE_BEARER_CUSTOMER,
    FEE_BEARER_MERCHANT,
    FEE_BEARER_PLATFORM,
    FEE_BEARER_SPLIT,
    FEE_BEARERS,
    PAYMENT_CHANNEL_BANK,
    PAYMENT_CHANNEL_BANK_TRANSFER,
    PAYMENT_CHANNEL_DVA,
    PAYMENT_CHANNEL_INTL_CARD,
    PAYMENT_CHANNEL_LOCAL_CARD,
    PAYMENT_CHANNEL_MOBILE_MONEY,
    PAYMENT_CHANNEL_QR,
    PAYMENT_CHANNEL_USSD,
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_TYPE_WITHDRAWAL,
)
from wallet.exceptions import InvalidAmount
from wallet.utils.money import ZERO, quantize, to_decimal

logger = logging.getLogger(__name__)

VALID_BEARERS = {choice for choice, _label in FEE_BEARERS}

SOURCE_DISABLED = 'disabled'
SOURCE_SETTINGS = 'settings'
SOURCE_DATABASE = 'database'
SOURCE_CUSTOM = 'custom'


def _dec(value, default='0'):
    return Decimal(str(value if value is not None else default))


class FeeCalculationResult:
    """
    Outcome of a fee calculation.

    ``customer_pays`` is what leaves the payer; ``merchant_receives`` is what
    reaches the receiver. ``total_amount`` / ``net_amount`` are aliases kept for
    backwards compatibility.
    """

    def __init__(self, original_amount, fee_amount, bearer, transaction_type, payment_channel=None,
                 source=SOURCE_SETTINGS, configuration=None, details=None, split_ratio=None):
        currency = original_amount.currency
        self.original_amount = original_amount
        self.fee_amount = Money(quantize(fee_amount.amount), currency)
        self.bearer = bearer
        self.transaction_type = transaction_type
        self.payment_channel = payment_channel
        self.source = source
        self.configuration = configuration
        self.details = details or {}

        fee = self.fee_amount.amount
        customer_fee, merchant_fee = ZERO, ZERO
        if bearer == FEE_BEARER_CUSTOMER:
            customer_fee = fee
        elif bearer == FEE_BEARER_MERCHANT:
            merchant_fee = fee
        elif bearer == FEE_BEARER_SPLIT:
            customer_pct, merchant_pct = split_ratio or (
                _dec(wallet_settings.FEE_SPLIT_CUSTOMER_PERCENTAGE),
                _dec(wallet_settings.FEE_SPLIT_MERCHANT_PERCENTAGE),
            )
            customer_fee = quantize(fee * _dec(customer_pct) / 100)
            merchant_fee = fee - customer_fee
            self.split_details = {
                'customer_fee': Money(customer_fee, currency),
                'merchant_fee': Money(merchant_fee, currency),
                'customer_percentage': _dec(customer_pct),
                'merchant_percentage': _dec(merchant_pct),
            }

        self.customer_fee = Money(customer_fee, currency)
        self.merchant_fee = Money(merchant_fee, currency)
        self.platform_fee = Money(fee if bearer == FEE_BEARER_PLATFORM else ZERO, currency)
        self.customer_pays = original_amount + self.customer_fee
        self.merchant_receives = original_amount - self.merchant_fee

        if self.merchant_receives.amount <= 0:
            raise InvalidAmount(
                message=f"Amount {original_amount} is too small to cover the fee of {self.fee_amount}"
            )

    # Aliases
    @property
    def payer_amount(self):
        return self.customer_pays

    @property
    def recipient_amount(self):
        return self.merchant_receives

    @property
    def total_amount(self):
        return self.customer_pays

    @property
    def net_amount(self):
        return self.merchant_receives

    @property
    def has_fee(self):
        return self.fee_amount.amount > 0

    def to_dict(self):
        result = {
            'original_amount': str(self.original_amount.amount),
            'fee_amount': str(self.fee_amount.amount),
            'currency': str(self.original_amount.currency),
            'bearer': self.bearer,
            'transaction_type': self.transaction_type,
            'payment_channel': self.payment_channel,
            'customer_fee': str(self.customer_fee.amount),
            'merchant_fee': str(self.merchant_fee.amount),
            'customer_pays': str(self.customer_pays.amount),
            'merchant_receives': str(self.merchant_receives.amount),
            'total_amount': str(self.total_amount.amount),
            'net_amount': str(self.net_amount.amount),
            'source': self.source,
        }
        if hasattr(self, 'split_details'):
            result['split_details'] = {
                'customer_fee': str(self.split_details['customer_fee'].amount),
                'merchant_fee': str(self.split_details['merchant_fee'].amount),
                'customer_percentage': str(self.split_details['customer_percentage']),
                'merchant_percentage': str(self.split_details['merchant_percentage']),
            }
        return result

    def __repr__(self):
        return (
            f"<FeeCalculationResult {self.transaction_type} amount={self.original_amount} "
            f"fee={self.fee_amount} bearer={self.bearer}>"
        )


class FeeCalculator:
    """
    Default fee calculator. Subclass and override :meth:`get_fee` for custom pricing.
    """

    def __init__(self, wallet=None, user=None):
        self.wallet = wallet
        self._user = user

    @property
    def user(self):
        """The paying user (loaded lazily - most pricing never needs it)."""
        if self._user is None and self.wallet is not None:
            self._user = self.wallet.user
        return self._user

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self, amount, transaction_type, payment_channel=None, is_international=False, bearer=None):
        amount = self._to_money(amount)
        if transaction_type == TRANSACTION_TYPE_DEPOSIT:
            if is_international:
                payment_channel = PAYMENT_CHANNEL_INTL_CARD
            payment_channel = payment_channel or PAYMENT_CHANNEL_LOCAL_CARD

        if not self.is_enabled(transaction_type, payment_channel):
            return FeeCalculationResult(
                amount, Money(ZERO, amount.currency),
                self.resolve_bearer(bearer, transaction_type, payment_channel), transaction_type,
                payment_channel, source=SOURCE_DISABLED,
            )

        fee, source, configuration, details = self.get_fee(amount.amount, transaction_type, payment_channel)
        chosen_bearer = self.resolve_bearer(bearer, transaction_type, payment_channel, configuration)
        split_ratio = None
        if configuration is not None and chosen_bearer == FEE_BEARER_SPLIT:
            split_ratio = (configuration.customer_percentage, configuration.merchant_percentage)

        # Paystack takes its percentage from the *total* charged, so a
        # customer-borne deposit fee must be grossed up to leave `amount` intact.
        if (transaction_type == TRANSACTION_TYPE_DEPOSIT and chosen_bearer == FEE_BEARER_CUSTOMER
                and wallet_settings.DEPOSIT_FEE_GROSS_UP):
            fee = self._gross_up(amount.amount, transaction_type, payment_channel)
            details = {**details, 'grossed_up': True}

        return FeeCalculationResult(
            amount, Money(fee, amount.currency), chosen_bearer, transaction_type, payment_channel,
            source=source, configuration=configuration, details=details, split_ratio=split_ratio,
        )

    # Backwards compatible entry points
    def calculate_amount_with_fees(self, amount, transaction_type, payment_channel=None, is_international=False,
                                   bearer=None):
        return self.calculate(amount, transaction_type, payment_channel, is_international, bearer)

    def calculate_deposit_fee(self, amount, payment_channel=PAYMENT_CHANNEL_LOCAL_CARD, is_international=False,
                              bearer=None):
        return self.calculate(amount, TRANSACTION_TYPE_DEPOSIT, payment_channel, is_international, bearer)

    def calculate_withdrawal_fee(self, amount, bearer=None):
        return self.calculate(amount, TRANSACTION_TYPE_WITHDRAWAL, bearer=bearer)

    def calculate_transfer_fee(self, amount, bearer=None):
        return self.calculate(amount, TRANSACTION_TYPE_TRANSFER, bearer=bearer)

    def calculate_payment_fee(self, amount, bearer=None):
        return self.calculate(amount, TRANSACTION_TYPE_PAYMENT, bearer=bearer)

    # ------------------------------------------------------------------
    # Extension points
    # ------------------------------------------------------------------

    def is_enabled(self, transaction_type, payment_channel=None):
        if not wallet_settings.ENABLE_FEES:
            return False
        if wallet_settings.USE_DATABASE_FEE_CONFIG and self._database_config(transaction_type, payment_channel):
            return True
        flags = {
            TRANSACTION_TYPE_DEPOSIT: 'ENABLE_DEPOSIT_FEES',
            TRANSACTION_TYPE_WITHDRAWAL: 'ENABLE_TRANSFER_FEES',
            TRANSACTION_TYPE_TRANSFER: 'ENABLE_INTERNAL_TRANSFER_FEES',
            TRANSACTION_TYPE_PAYMENT: 'ENABLE_PAYMENT_FEES',
        }
        flag = flags.get(transaction_type)
        return bool(flag and wallet_settings.get(flag))

    def get_fee(self, amount, transaction_type, payment_channel=None):
        """
        Return ``(fee: Decimal, source: str, configuration, details: dict)`` for ``amount`` (Decimal).

        Override this in a subclass to implement your own pricing.
        """
        if wallet_settings.USE_DATABASE_FEE_CONFIG:
            configuration = self._database_config(transaction_type, payment_channel)
            if configuration is not None:
                fee = configuration.calculate_fee(amount)
                return fee, SOURCE_DATABASE, configuration, {'configuration': str(configuration.id)}

        fee = self.settings_fee(amount, transaction_type, payment_channel)
        return fee, SOURCE_SETTINGS, None, {}

    def get_default_bearer(self, transaction_type, payment_channel=None):
        per_type = {
            TRANSACTION_TYPE_DEPOSIT: 'DEPOSIT_FEE_BEARER',
            TRANSACTION_TYPE_WITHDRAWAL: 'WITHDRAWAL_FEE_BEARER',
            TRANSACTION_TYPE_TRANSFER: 'TRANSFER_FEE_BEARER',
            TRANSACTION_TYPE_PAYMENT: 'PAYMENT_FEE_BEARER',
        }
        if transaction_type == TRANSACTION_TYPE_DEPOSIT and payment_channel == PAYMENT_CHANNEL_DVA:
            if wallet_settings.DVA_FEE_BEARER:
                return wallet_settings.DVA_FEE_BEARER
        name = per_type.get(transaction_type)
        return (wallet_settings.get(name) if name else None) or wallet_settings.DEFAULT_FEE_BEARER

    def resolve_bearer(self, bearer, transaction_type, payment_channel=None, configuration=None):
        if bearer:
            chosen = bearer
        elif configuration is not None and configuration.fee_bearer:
            chosen = configuration.fee_bearer
        else:
            chosen = self.get_default_bearer(transaction_type, payment_channel)
        if chosen not in VALID_BEARERS:
            raise InvalidAmount(message=f"Unknown fee bearer '{chosen}'")
        return chosen

    # ------------------------------------------------------------------
    # Settings based pricing
    # ------------------------------------------------------------------

    def settings_fee(self, amount, transaction_type, payment_channel=None):
        if transaction_type == TRANSACTION_TYPE_DEPOSIT:
            return self.deposit_fee(amount, payment_channel)
        if transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            return self.tiered_transfer_fee(amount)
        if transaction_type == TRANSACTION_TYPE_TRANSFER:
            return self._percentage_flat_cap(
                amount, wallet_settings.INTERNAL_TRANSFER_PERCENTAGE_FEE, wallet_settings.INTERNAL_TRANSFER_FLAT_FEE,
                wallet_settings.INTERNAL_TRANSFER_FEE_CAP,
            )
        if transaction_type == TRANSACTION_TYPE_PAYMENT:
            return self._percentage_flat_cap(
                amount, wallet_settings.PAYMENT_PERCENTAGE_FEE, wallet_settings.PAYMENT_FLAT_FEE,
                wallet_settings.PAYMENT_FEE_CAP,
            )
        return ZERO

    def deposit_fee(self, amount, payment_channel=None):
        channel = payment_channel or PAYMENT_CHANNEL_LOCAL_CARD
        if channel == PAYMENT_CHANNEL_INTL_CARD:
            return self._percentage_flat_cap(
                amount, wallet_settings.INTL_CARD_PERCENTAGE_FEE, wallet_settings.INTL_CARD_FLAT_FEE,
                wallet_settings.INTL_CARD_FEE_CAP,
            )
        if channel in (PAYMENT_CHANNEL_DVA, PAYMENT_CHANNEL_BANK_TRANSFER):
            return self._percentage_flat_cap(
                amount, wallet_settings.DVA_PERCENTAGE_FEE, wallet_settings.DVA_FLAT_FEE, wallet_settings.DVA_FEE_CAP,
            )
        if channel == PAYMENT_CHANNEL_MOBILE_MONEY:
            return self._percentage_flat_cap(
                amount, wallet_settings.MOBILE_MONEY_PERCENTAGE_FEE, wallet_settings.MOBILE_MONEY_FLAT_FEE,
                wallet_settings.MOBILE_MONEY_FEE_CAP,
            )
        # Local card, pay-with-bank, USSD, QR
        if wallet_settings.ENABLE_EDUCATIONAL_PRICING and channel in (
            PAYMENT_CHANNEL_LOCAL_CARD, PAYMENT_CHANNEL_BANK, PAYMENT_CHANNEL_USSD, PAYMENT_CHANNEL_QR,
        ):
            return self._percentage_flat_cap(
                amount, wallet_settings.EDUCATIONAL_CARD_PERCENTAGE_FEE, 0, wallet_settings.EDUCATIONAL_CARD_FEE_CAP,
            )
        threshold = wallet_settings.LOCAL_CARD_FEE_WAIVER_THRESHOLD
        flat = wallet_settings.LOCAL_CARD_FLAT_FEE
        if threshold is not None and amount < _dec(threshold):
            flat = 0
        return self._percentage_flat_cap(
            amount, wallet_settings.LOCAL_CARD_PERCENTAGE_FEE, flat, wallet_settings.LOCAL_CARD_FEE_CAP,
        )

    def tiered_transfer_fee(self, amount):
        tiers = sorted(
            wallet_settings.TRANSFER_FEE_TIERS or [],
            key=lambda tier: (tier.get('max_amount') is None, _dec(tier.get('max_amount') or 0)),
        )
        for tier in tiers:
            max_amount = tier.get('max_amount')
            if max_amount is None or amount <= _dec(max_amount):
                fee = _dec(tier.get('fee', 0))
                if tier.get('percentage'):
                    fee += amount * _dec(tier['percentage']) / 100
                return quantize(fee)
        return ZERO

    @staticmethod
    def _percentage_flat_cap(amount, percentage, flat, cap):
        fee = amount * _dec(percentage) / 100 + _dec(flat)
        if cap not in (None, '', 0) and fee > _dec(cap):
            fee = _dec(cap)
        return quantize(max(fee, ZERO))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gross_up(self, amount, transaction_type, payment_channel):
        """Smallest fee F such that fee(amount + F) <= F (the payer covers the fee on the fee)."""
        def fee_on(total):
            return self.get_fee(total, transaction_type, payment_channel)[0]

        total = amount + fee_on(amount)
        for _ in range(50):
            needed = amount + fee_on(total)
            if needed <= total:
                break
            total = needed
        return quantize(total - amount)

    def _database_config(self, transaction_type, payment_channel=None):
        from wallet.models import FeeConfiguration

        cache = self.__dict__.setdefault('_config_cache', {})
        key = (transaction_type, payment_channel)
        if key not in cache:
            cache[key] = FeeConfiguration.objects.for_transaction(self.wallet, transaction_type, payment_channel)
        return cache[key]

    def _to_money(self, amount):
        if isinstance(amount, Money):
            return Money(to_decimal(amount.amount), amount.currency)
        currency = self.wallet.currency if self.wallet is not None else wallet_settings.CURRENCY
        return Money(to_decimal(amount), currency)

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    @staticmethod
    def record_fee_history(transaction, fee_result):
        """Store how a transaction's fee was calculated. Never raises."""
        if fee_result is None or not fee_result.has_fee:
            return None
        from wallet.models import FeeHistory

        try:
            return FeeHistory.objects.create(
                transaction=transaction,
                configuration_used=fee_result.configuration,
                calculation_method=fee_result.source,
                original_amount=fee_result.original_amount,
                calculated_fee=fee_result.fee_amount,
                fee_bearer=fee_result.bearer,
                calculation_details={**fee_result.to_dict(), **{
                    k: str(v) for k, v in fee_result.details.items()
                }},
            )
        except Exception:  # pragma: no cover - audit must never break a payment
            logger.exception("Could not record fee history for transaction %s", transaction.pk)
            return None

    # Old private name
    _create_fee_history = record_fee_history


def get_fee_calculator(wallet=None, user=None):
    """Instantiate the calculator configured in ``WALLET_FEE_CALCULATOR``."""
    calculator_class = wallet_settings.import_from('FEE_CALCULATOR') or FeeCalculator
    return calculator_class(wallet=wallet, user=user)


def calculate_fee(amount, transaction_type, payment_channel=None, is_international=False, bearer=None, wallet=None,
                  user=None):
    """Convenience wrapper around the configured calculator."""
    return get_fee_calculator(wallet=wallet, user=user).calculate(
        amount, transaction_type, payment_channel, is_international, bearer,
    )


def paystack_channel_to_fee_channel(channel, authorization=None, integration_country=None):
    """Map a Paystack charge ``channel`` (+ card country) to the channel used for pricing."""
    country = (integration_country or wallet_settings.COUNTRY or '').upper()
    channel = (channel or '').lower()
    if channel == 'card':
        card_country = ((authorization or {}).get('country_code') or '').upper()
        if card_country and country and card_country != country:
            return PAYMENT_CHANNEL_INTL_CARD
        return PAYMENT_CHANNEL_LOCAL_CARD
    return {
        'dedicated_nuban': PAYMENT_CHANNEL_DVA,
        'bank_transfer': PAYMENT_CHANNEL_BANK_TRANSFER,
        'ussd': PAYMENT_CHANNEL_USSD,
        'qr': PAYMENT_CHANNEL_QR,
        'mobile_money': PAYMENT_CHANNEL_MOBILE_MONEY,
        'bank': PAYMENT_CHANNEL_BANK,
    }.get(channel, PAYMENT_CHANNEL_LOCAL_CARD)
