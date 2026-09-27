from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone
from djmoney.money import Money

from tests.conftest import fund, money
from wallet.exceptions import (
    CurrencyMismatchError,
    InsufficientFunds,
    InvalidAmount,
    InvalidPin,
    MinimumBalanceViolation,
    PinLocked,
    PinNotSet,
    RecipientError,
    WalletInactive,
    WalletLocked,
)
from wallet.models import BankAccount, Card, SettlementSchedule, Transaction, Wallet
from wallet.models.card import normalize_card_type
from wallet.services.wallet_service import WalletService

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Wallet balance primitives
# ---------------------------------------------------------------------------

def test_new_wallet_is_empty_and_ngn(wallet):
    assert wallet.balance == money(0)
    assert wallet.currency == 'NGN'
    assert wallet.is_operational


def test_credit_and_debit(wallet):
    assert wallet.credit(Decimal('500.50')) == money('500.50')
    assert wallet.debit(200) == money('300.50')
    wallet.refresh_from_db()
    assert wallet.balance == money('300.50')
    assert wallet.last_transaction_date is not None


def test_debit_rejects_overdraft(wallet):
    wallet.credit(100)
    with pytest.raises(InsufficientFunds):
        wallet.debit(100.01)
    wallet.refresh_from_db()
    assert wallet.balance == money(100)


@override_settings(WALLET_MINIMUM_BALANCE=50)
def test_minimum_balance(wallet):
    wallet.credit(100)
    with pytest.raises(MinimumBalanceViolation):
        wallet.debit(60)
    assert wallet.debit(50) == money(50)


@pytest.mark.parametrize('bad', [0, -5, 'abc', Decimal('-0.01')])
def test_invalid_amounts(wallet, bad):
    with pytest.raises(InvalidAmount):
        wallet.credit(bad)


def test_currency_mismatch(wallet):
    with pytest.raises(CurrencyMismatchError):
        wallet.credit(Money(10, 'USD'))


def test_locked_and_inactive_wallets(wallet):
    wallet.credit(100)
    wallet.lock('fraud check')
    with pytest.raises(WalletLocked):
        wallet.debit(10)
    with pytest.raises(WalletLocked):
        wallet.credit(10)
    assert wallet.credit(10, force=True) == money(110)
    wallet.unlock()
    wallet.deactivate()
    with pytest.raises(WalletInactive):
        wallet.debit(10)
    wallet.activate()
    assert wallet.debit(10) == money(100)


def test_debit_uses_fresh_balance_not_stale_instance(wallet):
    """A stale in-memory wallet must never allow spending money that is already gone."""
    fund(wallet, 100)
    stale = Wallet.objects.get(pk=wallet.pk)
    wallet.debit(80)
    with pytest.raises(InsufficientFunds):
        stale.debit(80)


# ---------------------------------------------------------------------------
# PIN
# ---------------------------------------------------------------------------

@override_settings(WALLET_PIN_MAX_ATTEMPTS=3)
def test_pin_lifecycle(wallet):
    with pytest.raises(PinNotSet):
        wallet.verify_pin('1234')
    wallet.set_pin('4826')
    assert wallet.has_pin
    assert wallet.pin_hash != '4826'
    assert wallet.verify_pin('4826')
    with pytest.raises(InvalidPin):
        wallet.verify_pin('0000')
    with pytest.raises(InvalidPin):
        wallet.verify_pin('0000')
    with pytest.raises(PinLocked):
        wallet.verify_pin('0000')
    with pytest.raises(PinLocked):
        wallet.verify_pin('4826')
    wallet.pin_locked_until = timezone.now() - timedelta(seconds=1)
    wallet.save()
    assert wallet.verify_pin('4826')
    wallet.clear_pin()
    assert not wallet.has_pin


# ---------------------------------------------------------------------------
# Daily limits
# ---------------------------------------------------------------------------

def test_daily_limit_settings_and_override(wallet):
    assert wallet.get_daily_limit() is None
    with override_settings(WALLET_MAXIMUM_DAILY_TRANSACTION=5000):
        assert wallet.get_daily_limit() == Decimal('5000')
        wallet.daily_limit = Decimal('100')
        assert wallet.get_daily_limit() == Decimal('100')


# ---------------------------------------------------------------------------
# Wallet service lifecycle
# ---------------------------------------------------------------------------

def test_get_wallet_is_idempotent(user, service):
    first = service.get_wallet(user)
    assert service.get_wallet(user).pk == first.pk
    assert Wallet.objects.filter(user=user).count() == 1
    assert first.tag == 'ada'


def test_tags_are_unique(django_user_model, service):
    a = django_user_model.objects.create_user(username='ada!', email='x@example.com')
    b = django_user_model.objects.create_user(username='ada', email='y@example.com')
    assert service.get_wallet(a).tag != service.get_wallet(b).tag


def test_phone_copied_from_user_field(django_user_model, service):
    user = django_user_model.objects.create_user(username='chi', email='chi@example.com', first_name='08031234567')
    with override_settings(WALLET_USER_PHONE_FIELD='first_name'):
        wallet = service.get_wallet(user)
    assert wallet.phone_number == '+2348031234567'


def test_invalid_or_taken_user_phone_is_ignored(django_user_model, service, wallet):
    service.set_phone_number(wallet, '08031234567')
    user = django_user_model.objects.create_user(username='chi', email='chi@example.com', first_name='08031234567')
    with override_settings(WALLET_USER_PHONE_FIELD='first_name'):
        assert service.get_wallet(user).phone_number is None


def test_set_phone_number_and_tag(service, wallet, other_wallet):
    service.set_phone_number(wallet, '0803 123 4567')
    assert wallet.phone_number == '+2348031234567'
    with pytest.raises(RecipientError):
        service.set_phone_number(other_wallet, '+2348031234567')
    service.set_phone_number(wallet, None)
    assert wallet.phone_number is None

    service.set_tag(wallet, '@Ada.Pay')
    assert wallet.tag == 'ada.pay'
    with pytest.raises(RecipientError):
        service.set_tag(other_wallet, 'ADA.PAY')
    with pytest.raises(RecipientError):
        service.set_tag(other_wallet, 'x')


@pytest.mark.django_db(transaction=True)
def test_wallet_created_automatically_for_new_users(django_user_model):
    user = django_user_model.objects.create_user(username='new', email='new@example.com')
    assert Wallet.objects.filter(user=user).exists()


@pytest.mark.django_db(transaction=True)
def test_auto_create_can_be_disabled(django_user_model, settings):
    settings.WALLET_AUTO_CREATE_WALLET = False
    user = django_user_model.objects.create_user(username='new', email='new@example.com')
    assert not Wallet.objects.filter(user=user).exists()


def test_paystack_provisioning_on_create(user, paystack, django_capture_on_commit_callbacks, settings):
    settings.WALLET_AUTO_CREATE_PAYSTACK_CUSTOMER = True
    settings.WALLET_AUTO_CREATE_DEDICATED_ACCOUNT = True
    settings.WALLET_DEDICATED_ACCOUNT_PROVIDER = 'test-bank'
    paystack.add('POST', 'customer', {'customer_code': 'CUS_ada', 'id': 11, 'identified': False})
    paystack.add('POST', 'dedicated_account', {
        'id': 77, 'account_number': '9930000001', 'account_name': 'ADA OBI', 'active': True,
        'bank': {'name': 'Test Bank', 'slug': 'test-bank'},
    })
    with django_capture_on_commit_callbacks(execute=True):
        wallet = WalletService().get_wallet(user)
    wallet.refresh_from_db()
    assert wallet.paystack_customer_code == 'CUS_ada'
    assert wallet.dedicated_account_number == '9930000001'
    assert paystack.last_body('dedicated_account')['preferred_bank'] == 'test-bank'


def test_provisioning_failure_does_not_block_wallet(user, paystack, django_capture_on_commit_callbacks, settings):
    settings.WALLET_AUTO_CREATE_PAYSTACK_CUSTOMER = True
    paystack.error('POST', 'customer', 'Invalid email')
    with django_capture_on_commit_callbacks(execute=True):
        wallet = WalletService().get_wallet(user)
    assert Wallet.objects.filter(pk=wallet.pk).exists()
    assert wallet.paystack_customer_code is None


def test_direct_credit_and_debit_create_ledger_rows(service, wallet):
    credit = service.credit_wallet(wallet, 1000, description='bonus')
    debit = service.debit_wallet(wallet, 250, description='charge')
    assert credit.direction == 'credit' and credit.balance_after == money(1000)
    assert debit.direction == 'debit' and debit.balance_after == money(750)
    statement = list(service.get_statement(wallet))
    assert [t.pk for t in statement] == [credit.pk, debit.pk]
    # legacy names
    assert service.deposit(wallet, 50).is_successful
    assert service.withdraw(wallet, 50).is_successful


def test_lock_unlock_signals(service, wallet, django_capture_on_commit_callbacks):
    from wallet.signals import wallet_locked, wallet_unlocked
    received = []
    wallet_locked.connect(lambda **kw: received.append('locked'), weak=False, dispatch_uid='t1')
    wallet_unlocked.connect(lambda **kw: received.append('unlocked'), weak=False, dispatch_uid='t2')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            service.lock_wallet_account(wallet, 'kyc')
            service.unlock_wallet_account(wallet)
    finally:
        wallet_locked.disconnect(dispatch_uid='t1')
        wallet_unlocked.disconnect(dispatch_uid='t2')
    assert received == ['locked', 'unlocked']


# ---------------------------------------------------------------------------
# Other models
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [('visa ', 'visa'), ('VISA DEBIT', 'visa'), ('mastercard', 'mastercard'),
                                          ('Verve', 'verve'), ('american express', 'amex'), ('', 'other'),
                                          ('unionpay', 'other')])
def test_card_type_normalisation(raw, expected):
    assert normalize_card_type(raw) == expected


def test_card_defaults_and_removal(wallet, card):
    second = Card.objects.create(wallet=wallet, last_four='1111', expiry_month='01', expiry_year='2099',
                                 paystack_authorization_code='AUTH_2', is_default=True)
    card.refresh_from_db()
    assert not card.is_default
    second.remove()
    card.refresh_from_db()
    assert card.is_default and not second.is_active
    assert card.masked_pan == '408408 **** **** 4081'
    assert not card.is_expired
    card.expiry_year = '2000'
    assert card.is_expired and not card.is_valid


def test_bank_account_default_switching(wallet, bank, bank_account):
    other = BankAccount.objects.create(wallet=wallet, bank=bank, account_number='9999999999', account_name='A',
                                       is_default=True)
    bank_account.refresh_from_db()
    assert not bank_account.is_default
    other.remove()
    bank_account.refresh_from_db()
    assert bank_account.is_default
    assert bank_account.masked_account_number == '******6789'
    assert bank_account.can_receive_transfers


def _aware(year, month, day, hour=0, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


@pytest.mark.parametrize('schedule_type,kwargs,now,expected', [
    ('daily', {'time_of_day': time(9, 0)}, _aware(2026, 1, 5, 8), _aware(2026, 1, 5, 9)),
    ('daily', {'time_of_day': time(9, 0)}, _aware(2026, 1, 5, 10), _aware(2026, 1, 6, 9)),
    ('weekly', {'day_of_week': 4}, _aware(2026, 1, 5, 10), _aware(2026, 1, 9)),        # Mon -> Fri
    ('weekly', {'day_of_week': 0}, _aware(2026, 1, 5, 10), _aware(2026, 1, 12)),       # Mon after midnight -> next Mon
    ('monthly', {'day_of_month': 31}, _aware(2026, 2, 3), _aware(2026, 2, 28)),         # clamps to month end
    ('monthly', {'day_of_month': 15}, _aware(2026, 12, 20), _aware(2027, 1, 15)),       # rolls into next year
    ('threshold', {}, _aware(2026, 1, 1), None),
    ('manual', {}, _aware(2026, 1, 1), None),
])
def test_schedule_next_run(wallet, bank_account, schedule_type, kwargs, now, expected):
    schedule = SettlementSchedule(wallet=wallet, bank_account=bank_account, schedule_type=schedule_type, **kwargs)
    assert schedule.compute_next_settlement(after=now) == expected


def test_schedule_validation(wallet, bank_account):
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        SettlementSchedule(wallet=wallet, bank_account=bank_account, schedule_type='weekly').clean()
    with pytest.raises(ValidationError):
        SettlementSchedule(wallet=wallet, bank_account=bank_account, schedule_type='monthly', day_of_month=40).clean()
    with pytest.raises(ValidationError):
        SettlementSchedule(wallet=wallet, bank_account=bank_account, schedule_type='threshold').clean()


def test_transaction_reference_and_flags(wallet):
    txn = Transaction.objects.create(wallet=wallet, amount=money(10), transaction_type='deposit')
    assert txn.reference.startswith('TRX-')
    assert txn.is_pending and not txn.is_final and txn.can_be_cancelled()
    assert not txn.can_be_refunded() and not txn.can_be_reversed()
    assert txn.net_amount == money(10)


def test_ledger_sequence_orders_entries_with_identical_timestamps(service, wallet, other_wallet):
    """Clock resolution can give consecutive entries the same created_at; the statement must stay ordered."""
    fund(wallet, 1000)
    service.transfer(wallet, other_wallet, 100)
    service.transfer(wallet, other_wallet, 200)
    Transaction.objects.filter(wallet=wallet).update(created_at=timezone.now())
    rows = list(service.get_statement(wallet))
    assert [r.ledger_sequence for r in rows] == [1, 2, 3]
    assert [r.balance_after for r in rows] == [money(1000), money(900), money(700)]
    wallet.refresh_from_db()
    assert wallet.ledger_sequence == 3
    assert [r.ledger_sequence for r in service.get_statement(other_wallet)] == [1, 2]


def test_pending_entries_have_no_sequence(wallet):
    txn = Transaction.objects.create(wallet=wallet, amount=money(10), transaction_type='deposit')
    assert txn.ledger_sequence is None


@pytest.mark.django_db(transaction=True)
def test_locked_fast_path_requires_a_transaction(user):
    """credit(locked=True) skips re-locking, so it must refuse to run outside a transaction."""
    from django.db import transaction
    wallet = WalletService().get_wallet(user)
    with pytest.raises(RuntimeError):
        wallet.credit(50, locked=True)          # autocommit mode: no lock could be held
    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
        assert locked.credit(50, locked=True) == money(50)
    wallet.refresh_from_db()
    assert wallet.balance == money(50) and wallet.ledger_sequence == 1


def test_transfer_query_budget(service, wallet, other_wallet, django_assert_max_num_queries):
    fund(wallet, 1000)
    with django_assert_max_num_queries(10):
        service.transfer(wallet, other_wallet, 10)
