from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from tests.conftest import money
from wallet.constants import (
    PAYMENT_CHANNEL_BANK_TRANSFER,
    PAYMENT_CHANNEL_DVA,
    PAYMENT_CHANNEL_INTL_CARD,
    PAYMENT_CHANNEL_LOCAL_CARD,
    PAYMENT_CHANNEL_MOBILE_MONEY,
)
from wallet.exceptions import InvalidAmount
from wallet.models import FeeConfiguration, FeeHistory, FeeTier
from wallet.services.fee_service import (
    FeeCalculator,
    calculate_fee,
    get_fee_calculator,
    paystack_channel_to_fee_channel,
)

FEES_ON = dict(WALLET_ENABLE_FEES=True)
D = Decimal


def calc(amount, kind, channel=None, bearer=None, wallet=None, **kwargs):
    return FeeCalculator(wallet=wallet).calculate(money(amount), kind, channel, bearer=bearer, **kwargs)


# ---------------------------------------------------------------------------
# Master switch
# ---------------------------------------------------------------------------

def test_fees_off_by_default():
    result = calc(10000, 'deposit', bearer='customer')
    assert result.fee_amount.amount == 0
    assert result.source == 'disabled'
    assert result.customer_pays == result.merchant_receives == money(10000)


# ---------------------------------------------------------------------------
# Deposit pricing (Paystack Nigeria defaults)
# ---------------------------------------------------------------------------

@override_settings(**FEES_ON)
@pytest.mark.parametrize('amount,expected', [
    (1000, '15.00'),      # 1.5%, flat waived under 2,500
    (2499, '37.49'),
    (2500, '137.50'),     # 1.5% + 100
    (10000, '250.00'),
    (200000, '2000.00'),  # capped
])
def test_local_card_fee(amount, expected):
    assert calc(amount, 'deposit', PAYMENT_CHANNEL_LOCAL_CARD, bearer='merchant').fee_amount.amount == D(expected)


@override_settings(**FEES_ON)
def test_international_card_fee_uncapped():
    assert calc(100000, 'deposit', PAYMENT_CHANNEL_INTL_CARD, bearer='merchant').fee_amount.amount == D('4000.00')
    assert calc(100000, 'deposit', is_international=True, bearer='merchant').fee_amount.amount == D('4000.00')


@override_settings(**FEES_ON)
@pytest.mark.parametrize('channel', [PAYMENT_CHANNEL_DVA, PAYMENT_CHANNEL_BANK_TRANSFER])
def test_dva_fee_is_one_percent_capped_at_300(channel):
    assert calc(10000, 'deposit', channel, bearer='merchant').fee_amount.amount == D('100.00')
    assert calc(100000, 'deposit', channel, bearer='merchant').fee_amount.amount == D('300.00')


@override_settings(**FEES_ON)
def test_mobile_money_fee():
    assert calc(1000, 'deposit', PAYMENT_CHANNEL_MOBILE_MONEY, bearer='merchant').fee_amount.amount == D('19.50')


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_EDUCATIONAL_PRICING=True)
def test_educational_pricing():
    assert calc(10000, 'deposit', bearer='merchant').fee_amount.amount == D('70.00')
    assert calc(1000000, 'deposit', bearer='merchant').fee_amount.amount == D('1500.00')


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_DEPOSIT_FEES=False)
def test_deposit_fees_can_be_switched_off_alone():
    assert calc(10000, 'deposit', bearer='merchant').fee_amount.amount == 0
    assert calc(10000, 'withdrawal').fee_amount.amount == D('25.00')


# ---------------------------------------------------------------------------
# Bearers
# ---------------------------------------------------------------------------

@override_settings(**FEES_ON)
def test_merchant_bearer_deducts_from_receiver():
    result = calc(10000, 'deposit', bearer='merchant')
    assert result.customer_pays == money(10000)
    assert result.merchant_receives == money('9750.00')


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_GROSS_UP=False)
def test_customer_bearer_without_gross_up():
    result = calc(10000, 'deposit', bearer='customer')
    assert result.customer_pays == money('10250.00')
    assert result.merchant_receives == money(10000)


@override_settings(**FEES_ON)
@pytest.mark.parametrize('amount', [100, 2400, 2463, 5000, 10000, 123456, 500000])
def test_customer_bearer_gross_up_leaves_exact_amount(amount):
    """After Paystack takes its fee from the grossed-up charge, at least `amount` must remain."""
    result = calc(amount, 'deposit', bearer='customer')
    charged = result.customer_pays.amount
    paystack_fee = FeeCalculator().deposit_fee(charged, PAYMENT_CHANNEL_LOCAL_CARD)
    assert charged - paystack_fee >= D(amount)
    assert charged - paystack_fee - D(amount) <= D('0.02')
    assert result.merchant_receives == money(amount)


@override_settings(**FEES_ON)
def test_platform_bearer_charges_nobody():
    result = calc(10000, 'deposit', bearer='platform')
    assert result.fee_amount.amount == D('250.00')
    assert result.platform_fee.amount == D('250.00')
    assert result.customer_pays == result.merchant_receives == money(10000)


@override_settings(WALLET_ENABLE_FEES=True, WALLET_FEE_SPLIT_CUSTOMER_PERCENTAGE=30,
                   WALLET_FEE_SPLIT_MERCHANT_PERCENTAGE=70, WALLET_DEPOSIT_FEE_GROSS_UP=False)
def test_split_bearer():
    result = calc(10000, 'deposit', bearer='split')
    assert result.customer_fee.amount == D('75.00')
    assert result.merchant_fee.amount == D('175.00')
    assert result.customer_pays == money('10075.00')
    assert result.merchant_receives == money('9825.00')
    assert result.to_dict()['split_details']['customer_percentage'] == '30'


@override_settings(**FEES_ON)
def test_split_rounding_keeps_total_exact():
    result = calc(3333, 'deposit', bearer='split')
    assert result.customer_fee.amount + result.merchant_fee.amount == result.fee_amount.amount


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEFAULT_FEE_BEARER='merchant', WALLET_DEPOSIT_FEE_BEARER=None)
def test_default_bearer_resolution():
    assert calc(1000, 'deposit').bearer == 'merchant'
    assert calc(1000, 'withdrawal').bearer == 'customer'          # WALLET_WITHDRAWAL_FEE_BEARER default
    assert calc(1000, 'deposit', PAYMENT_CHANNEL_DVA).bearer == 'merchant'


def test_unknown_bearer_rejected():
    with pytest.raises(InvalidAmount):
        calc(1000, 'deposit', bearer='nobody')


@override_settings(**FEES_ON)
def test_amount_too_small_for_merchant_fee():
    with override_settings(WALLET_ENABLE_INTERNAL_TRANSFER_FEES=True, WALLET_INTERNAL_TRANSFER_FLAT_FEE=50):
        with pytest.raises(InvalidAmount):
            calc(40, 'transfer', bearer='merchant')


# ---------------------------------------------------------------------------
# Withdrawals, transfers, payments
# ---------------------------------------------------------------------------

@override_settings(**FEES_ON)
@pytest.mark.parametrize('amount,expected', [(100, '10.00'), (5000, '10.00'), (5001, '25.00'), (50000, '25.00'),
                                             (50001, '50.00'), (10000000, '50.00')])
def test_withdrawal_tiers(amount, expected):
    result = calc(amount, 'withdrawal')
    assert result.fee_amount.amount == D(expected)
    assert result.customer_pays == money(amount) + result.fee_amount   # wallet owner pays on top by default


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_TRANSFER_FEES=False)
def test_withdrawal_fees_switch():
    assert calc(10000, 'withdrawal').fee_amount.amount == 0


@override_settings(WALLET_ENABLE_FEES=True, WALLET_TRANSFER_FEE_TIERS=[
    {'max_amount': None, 'fee': 5, 'percentage': 1}, {'max_amount': 100, 'fee': 1}])
def test_custom_tiers_are_sorted_and_support_percentage():
    assert calc(50, 'withdrawal').fee_amount.amount == D('1.00')
    assert calc(1000, 'withdrawal').fee_amount.amount == D('15.00')


def test_internal_transfers_free_by_default():
    with override_settings(**FEES_ON):
        assert calc(10000, 'transfer').fee_amount.amount == 0


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_INTERNAL_TRANSFER_FEES=True,
                   WALLET_INTERNAL_TRANSFER_PERCENTAGE_FEE=D('0.5'), WALLET_INTERNAL_TRANSFER_FLAT_FEE=10,
                   WALLET_INTERNAL_TRANSFER_FEE_CAP=100, WALLET_TRANSFER_FEE_BEARER='customer')
def test_internal_transfer_fee():
    assert calc(1000, 'transfer').fee_amount.amount == D('15.00')
    assert calc(1000000, 'transfer').fee_amount.amount == D('100.00')


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_PAYMENT_FEES=True, WALLET_PAYMENT_PERCENTAGE_FEE=5,
                   WALLET_PAYMENT_FEE_BEARER='merchant')
def test_marketplace_commission():
    result = calc(20000, 'payment')
    assert result.fee_amount.amount == D('1000.00')
    assert result.merchant_receives == money(19000)
    assert result.customer_pays == money(20000)


# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDatabaseFees:

    @pytest.fixture(autouse=True)
    def _database_pricing(self, settings):
        settings.WALLET_ENABLE_FEES = True
        settings.WALLET_USE_DATABASE_FEE_CONFIG = True

    def test_global_config(self):
        FeeConfiguration.objects.create(name='g', transaction_type='withdrawal', fee_type='flat', flat_fee=money(7))
        result = calc(1000, 'withdrawal')
        assert result.fee_amount.amount == D('7.00')
        assert result.source == 'database'

    def test_wallet_config_beats_global_and_channel_beats_generic(self, wallet):
        FeeConfiguration.objects.create(name='g', transaction_type='deposit', fee_type='flat', flat_fee=money(1))
        FeeConfiguration.objects.create(name='w', transaction_type='deposit', fee_type='flat', flat_fee=money(2),
                                        wallet=wallet)
        FeeConfiguration.objects.create(name='wc', transaction_type='deposit', fee_type='flat', flat_fee=money(3),
                                        wallet=wallet, payment_channel=PAYMENT_CHANNEL_DVA)
        assert calc(1000, 'deposit', PAYMENT_CHANNEL_DVA, 'merchant', wallet).fee_amount.amount == D('3.00')
        assert calc(1000, 'deposit', PAYMENT_CHANNEL_LOCAL_CARD, 'merchant', wallet).fee_amount.amount == D('2.00')
        assert calc(1000, 'deposit', PAYMENT_CHANNEL_LOCAL_CARD, 'merchant').fee_amount.amount == D('1.00')

    def test_priority_and_validity_window(self):
        now = timezone.now()
        FeeConfiguration.objects.create(name='low', transaction_type='transfer', fee_type='flat', flat_fee=money(1),
                                        priority=1)
        FeeConfiguration.objects.create(name='expired', transaction_type='transfer', fee_type='flat',
                                        flat_fee=money(9), priority=10, valid_until=now - timedelta(days=1))
        FeeConfiguration.objects.create(name='future', transaction_type='transfer', fee_type='flat',
                                        flat_fee=money(8), priority=10, valid_from=now + timedelta(days=1))
        FeeConfiguration.objects.create(name='inactive', transaction_type='transfer', fee_type='flat',
                                        flat_fee=money(6), priority=10, is_active=False)
        FeeConfiguration.objects.create(name='high', transaction_type='transfer', fee_type='flat', flat_fee=money(4),
                                        priority=5)
        assert calc(1000, 'transfer', bearer='customer').fee_amount.amount == D('4.00')

    def test_hybrid_with_waiver_minimum_and_cap(self):
        FeeConfiguration.objects.create(
            name='h', transaction_type='payment', fee_type='hybrid', percentage_fee=D('2'), flat_fee=money(50),
            waiver_threshold=money(1000), minimum_fee=money(5), fee_cap=money(300), fee_bearer='merchant',
        )
        assert calc(100, 'payment').fee_amount.amount == D('5.00')      # 2 -> minimum 5, flat waived
        assert calc(2000, 'payment').fee_amount.amount == D('90.00')    # 40 + 50
        assert calc(50000, 'payment').fee_amount.amount == D('300.00')  # capped
        assert calc(2000, 'payment').bearer == 'merchant'               # bearer from config

    def test_tiered_config(self):
        config = FeeConfiguration.objects.create(name='t', transaction_type='withdrawal', fee_type='tiered')
        FeeTier.objects.create(configuration=config, min_amount=money(0), max_amount=money(1000), fee_amount=money(5))
        FeeTier.objects.create(configuration=config, min_amount=money('1000.01'), fee_amount=money(10),
                               percentage_fee=D('0.1'))
        assert calc(500, 'withdrawal').fee_amount.amount == D('5.00')
        assert calc(10000, 'withdrawal').fee_amount.amount == D('20.00')

    def test_split_ratio_from_config(self):
        FeeConfiguration.objects.create(name='s', transaction_type='transfer', fee_type='flat', flat_fee=money(100),
                                        fee_bearer='split', customer_percentage=25, merchant_percentage=75)
        result = calc(1000, 'transfer')
        assert result.customer_fee.amount == D('25.00')
        assert result.merchant_fee.amount == D('75.00')

    def test_db_config_applies_even_when_type_switch_off(self):
        FeeConfiguration.objects.create(name='t', transaction_type='transfer', fee_type='flat', flat_fee=money(3))
        assert calc(1000, 'transfer', bearer='customer').fee_amount.amount == D('3.00')

    def test_config_validation(self):
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            FeeConfiguration(name='bad', transaction_type='deposit', fee_bearer='split', customer_percentage=60,
                             merchant_percentage=60).clean()
        with pytest.raises(ValidationError):
            FeeConfiguration(name='bad', transaction_type='deposit', fee_type='percentage', percentage_fee=0).clean()

    def test_fee_history_recorded(self, funded_wallet):
        FeeConfiguration.objects.create(name='g', transaction_type='withdrawal', fee_type='flat', flat_fee=money(7))
        from wallet.models import Transaction
        txn = Transaction.objects.filter(wallet=funded_wallet).first()
        result = calc(1000, 'withdrawal')
        history = FeeCalculator.record_fee_history(txn, result)
        assert history.calculated_fee == money(7)
        assert history.configuration_used is not None
        assert FeeHistory.objects.count() == 1


# ---------------------------------------------------------------------------
# Pluggability & helpers
# ---------------------------------------------------------------------------

@override_settings(WALLET_FEE_CALCULATOR='tests.helpers.FlatTenCalculator')
def test_custom_calculator_setting():
    calculator = get_fee_calculator()
    assert type(calculator).__name__ == 'FlatTenCalculator'
    result = calculate_fee(money(5000), 'transfer', bearer='customer')
    assert result.fee_amount.amount == D('10.00')
    assert result.source == 'custom'


def test_to_dict_is_json_friendly():
    import json
    with override_settings(**FEES_ON):
        data = calc(10000, 'deposit', bearer='merchant').to_dict()
    json.dumps(data)
    assert data['fee_amount'] == '250.00'
    assert data['merchant_receives'] == '9750.00'


@override_settings(WALLET_COUNTRY='NG')
@pytest.mark.parametrize('channel,auth,expected', [
    ('card', {'country_code': 'NG'}, PAYMENT_CHANNEL_LOCAL_CARD),
    ('card', {'country_code': 'US'}, PAYMENT_CHANNEL_INTL_CARD),
    ('card', {}, PAYMENT_CHANNEL_LOCAL_CARD),
    ('dedicated_nuban', {}, PAYMENT_CHANNEL_DVA),
    ('bank_transfer', {}, PAYMENT_CHANNEL_BANK_TRANSFER),
    ('mobile_money', {}, PAYMENT_CHANNEL_MOBILE_MONEY),
    ('weird', {}, PAYMENT_CHANNEL_LOCAL_CARD),
])
def test_channel_mapping(channel, auth, expected):
    assert paystack_channel_to_fee_channel(channel, auth) == expected
