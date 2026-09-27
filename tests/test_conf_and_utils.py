from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from djmoney.money import Money

from wallet.conf import _parse_env, get_wallet_setting, is_feature_enabled, setting_name, wallet_settings
from wallet.exceptions import InvalidAmount, InvalidPhoneNumber
from wallet.settings import WALLET_SETTINGS
from wallet.utils.id_generators import generate_transfer_reference, generate_wallet_tag
from wallet.utils.money import from_minor_units, to_decimal, to_minor_units, to_money
from wallet.utils.phone import (
    default_normalize_phone_number,
    looks_like_phone_number,
    mask_phone_number,
    normalize_phone_number,
)


# ---------------------------------------------------------------------------
# Settings resolution
# ---------------------------------------------------------------------------

def test_defaults_are_used():
    assert wallet_settings.CURRENCY == 'NGN'
    assert wallet_settings.ENABLE_FEES is False


def test_django_settings_override_defaults():
    with override_settings(WALLET_CURRENCY='GHS', WALLET_ENABLE_FEES=True):
        assert wallet_settings.CURRENCY == 'GHS'
        assert get_wallet_setting('ENABLE_FEES') is True
    assert wallet_settings.CURRENCY == 'NGN'


def test_paystack_keys_use_unprefixed_names():
    assert setting_name('PAYSTACK_SECRET_KEY') == 'PAYSTACK_SECRET_KEY'
    assert setting_name('CURRENCY') == 'WALLET_CURRENCY'
    assert wallet_settings.PAYSTACK_SECRET_KEY.startswith('sk_test_')


def test_environment_variables_are_read(monkeypatch):
    monkeypatch.setenv('WALLET_ENABLE_WEBHOOK_FORWARDING', 'true')
    monkeypatch.setenv('WALLET_API_PAGE_SIZE', '50')
    monkeypatch.setenv('WALLET_LOCAL_CARD_FEE_CAP', '1500.50')
    monkeypatch.setenv('WALLET_WEBHOOK_ALLOWED_IPS', '1.1.1.1, 2.2.2.2')
    monkeypatch.setenv('WALLET_MAXIMUM_DAILY_TRANSACTION', '250000')
    monkeypatch.setenv('WALLET_TRANSFER_FEE_TIERS', '[{"max_amount": null, "fee": 5}]')
    assert wallet_settings.ENABLE_WEBHOOK_FORWARDING is True
    assert wallet_settings.API_PAGE_SIZE == 50
    assert wallet_settings.LOCAL_CARD_FEE_CAP == Decimal('1500.50')
    assert wallet_settings.WEBHOOK_ALLOWED_IPS == ['1.1.1.1', '2.2.2.2']
    assert wallet_settings.MAXIMUM_DAILY_TRANSACTION == Decimal('250000')
    assert wallet_settings.TRANSFER_FEE_TIERS == [{'max_amount': None, 'fee': 5}]


def test_django_setting_beats_environment(monkeypatch):
    monkeypatch.setenv('WALLET_CURRENCY', 'KES')
    assert wallet_settings.CURRENCY == 'KES'
    with override_settings(WALLET_CURRENCY='ZAR'):
        assert wallet_settings.CURRENCY == 'ZAR'


@pytest.mark.parametrize('raw,default,expected', [
    ('yes', False, True), ('0', True, False), ('off', True, False), ('', True, True), ('  ', 5, 5),
    ('7', 1, 7), ('none', None, None), ('null', 'x', None), ('wema-bank', None, 'wema-bank'),
    ('12', None, Decimal('12')), ('true', None, True), ('["a"]', None, ['a']), ('{"a": 1}', {}, {'a': 1}),
])
def test_parse_env(raw, default, expected):
    assert _parse_env(raw, default) == expected


def test_parse_env_rejects_bad_boolean():
    with pytest.raises(ImproperlyConfigured):
        _parse_env('maybe', True)


def test_unknown_and_removed_settings():
    with pytest.raises(ValueError):
        get_wallet_setting('NOT_A_SETTING')
    with pytest.raises(ImproperlyConfigured):
        wallet_settings.get('USE_UUID')


def test_mutable_defaults_are_copied():
    tiers = wallet_settings.TRANSFER_FEE_TIERS
    tiers.append({'max_amount': None, 'fee': 1})
    assert len(wallet_settings.TRANSFER_FEE_TIERS) == 3


def test_feature_switches():
    assert is_feature_enabled('withdrawals')
    with override_settings(WALLET_ENABLE_WITHDRAWALS=False):
        assert not is_feature_enabled('WITHDRAWALS')


def test_as_dict_masks_secret():
    resolved = wallet_settings.as_dict()
    assert '...' in resolved['PAYSTACK_SECRET_KEY']
    assert 'sk_test_0000000000000000000000000000000000000000' not in str(resolved)


def test_import_from_reports_bad_path():
    with override_settings(WALLET_FEE_CALCULATOR='nope.Missing'):
        with pytest.raises(ImproperlyConfigured):
            wallet_settings.import_from('FEE_CALCULATOR')


def test_legacy_settings_dict():
    assert WALLET_SETTINGS['CURRENCY'] == 'NGN'
    assert 'CURRENCY' in WALLET_SETTINGS
    assert WALLET_SETTINGS.get('NOPE', 1) == 1


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw', [
    '08031234567', '8031234567', '2348031234567', '+2348031234567', '+234 803 123 4567', '(0803) 123-4567',
    '002348031234567',
])
def test_nigerian_numbers_normalise_to_e164(raw):
    assert normalize_phone_number(raw) == '+2348031234567'


def test_other_country_code():
    assert default_normalize_phone_number('0241234567', country_code='233') == '+233241234567'


@pytest.mark.parametrize('raw', ['', None, 'abc', '12', '+12345678901234567'])
def test_invalid_numbers(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone_number(raw)


def test_custom_normalizer():
    with override_settings(WALLET_PHONE_NUMBER_NORMALIZER='tests.helpers.upper_normalizer'):
        assert normalize_phone_number('abc') == 'ABC'


def test_phone_helpers():
    assert looks_like_phone_number('0803 123 4567')
    assert not looks_like_phone_number('ada')
    assert mask_phone_number('+2348031234567') == '+234803****567'


# ---------------------------------------------------------------------------
# Money & references
# ---------------------------------------------------------------------------

def test_money_conversions():
    assert to_minor_units(Decimal('10.505')) == 1051
    assert to_minor_units(100) == 10000
    assert from_minor_units(1050) == Decimal('10.50')
    assert from_minor_units(None) == Decimal('0.00')
    assert to_decimal(Money(5, 'NGN')) == Decimal('5.00')
    assert to_money('12.3').amount == Decimal('12.30')
    with pytest.raises(InvalidAmount):
        to_decimal('abc')
    with pytest.raises(InvalidAmount):
        to_decimal(None)


def test_transfer_references_follow_paystack_rules():
    reference = generate_transfer_reference()
    assert reference == reference.lower()
    assert 16 <= len(reference) <= 50


def test_wallet_tag_from_user(user):
    assert generate_wallet_tag(user) == 'ada'
    assert generate_wallet_tag(None).startswith('w')


def test_env_example_documents_every_setting():
    """Keep .env.example in sync with wallet.conf.DEFAULTS."""
    from pathlib import Path

    from wallet.conf import DEFAULTS

    text = (Path(__file__).resolve().parent.parent / '.env.example').read_text(encoding='utf-8')
    missing = [setting_name(name) for name in DEFAULTS if f"{setting_name(name)}=" not in text]
    assert missing == []


def test_env_example_values_parse(monkeypatch):
    """Every example value in .env.example must be accepted by the parser."""
    from pathlib import Path

    from wallet.conf import DEFAULTS

    text = (Path(__file__).resolve().parent.parent / '.env.example').read_text(encoding='utf-8')
    names = {setting_name(name): name for name in DEFAULTS}
    for line in text.splitlines():
        line = line.lstrip('# ').strip()
        if '=' not in line or not line.split('=', 1)[0] in names:
            continue
        key, value = line.split('=', 1)
        monkeypatch.setenv(key, value)
        parsed = wallet_settings.get(names[key])
        default = DEFAULTS[names[key]]
        if default is not None and not isinstance(default, str):
            assert isinstance(parsed, type(default)) or isinstance(parsed, (list, dict)), (key, parsed)
        if value == '':
            assert parsed == default, key


def test_empty_env_values_mean_default(monkeypatch, wallet):
    monkeypatch.setenv('WALLET_MINIMUM_TRANSACTION_AMOUNT', '')
    monkeypatch.setenv('WALLET_MINIMUM_BALANCE', '')
    monkeypatch.setenv('WALLET_ENABLE_DEPOSITS', '')
    assert wallet_settings.MINIMUM_TRANSACTION_AMOUNT is None
    assert wallet_settings.MINIMUM_BALANCE == 0
    assert wallet_settings.ENABLE_DEPOSITS is True
    wallet.credit(10)
    assert wallet.debit(5).amount == 5


def test_load_env_file(tmp_path, monkeypatch):
    from wallet.conf import load_env_file

    env = tmp_path / '.env'
    env.write_text(
        '# comment\n'
        'WALLET_CURRENCY="GHS"\n'
        "export WALLET_API_PAGE_SIZE='15'\n"
        'WALLET_ENABLE_FEES=true  # inline comment\n'
        'WALLET_COUNTRY=GH\n'
        'not a setting line\n',
        encoding='utf-8',
    )
    for key in ('WALLET_CURRENCY', 'WALLET_API_PAGE_SIZE', 'WALLET_ENABLE_FEES'):
        monkeypatch.setenv(key, 'x')     # records the original state so teardown restores it...
        monkeypatch.delenv(key)          # ...then start from "unset"
    monkeypatch.setenv('WALLET_COUNTRY', 'NG')          # real environment wins

    assert load_env_file(env) == 3
    assert wallet_settings.CURRENCY == 'GHS'
    assert wallet_settings.API_PAGE_SIZE == 15
    assert wallet_settings.ENABLE_FEES is True
    assert wallet_settings.COUNTRY == 'NG'
    assert load_env_file(env, override=True) == 4
    assert wallet_settings.COUNTRY == 'GH'
    assert load_env_file(tmp_path / 'missing.env') == 0


def test_load_env_file_does_not_leak():
    import os
    assert 'WALLET_CURRENCY' not in os.environ
    assert wallet_settings.CURRENCY == 'NGN'
