from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from tests.conftest import charge_data, money
from wallet.exceptions import (
    CardError,
    DuplicateReference,
    FeatureDisabled,
    InvalidAmount,
    PaystackAPIError,
    WalletLocked,
)
from wallet.models import Card, FeeHistory, Transaction
from wallet.services.deposit_service import DepositService
from wallet.signals import deposit_completed, deposit_failed

pytestmark = pytest.mark.django_db

INIT_RESPONSE = {'authorization_url': 'https://checkout.paystack.com/abc', 'access_code': 'abc', 'reference': 'x'}


def init(service, paystack, wallet, amount=5000, **kwargs):
    paystack.add('POST', 'transaction/initialize', INIT_RESPONSE)
    return service.initialize_deposit(wallet, amount, **kwargs)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_initialize_creates_pending_deposit_and_calls_paystack(service, paystack, wallet):
    result = init(service, paystack, wallet, 5000, callback_url='https://shop.test/cb', metadata={'order': 7})
    txn = Transaction.objects.get(reference=result['reference'])
    assert txn.status == 'pending' and txn.direction == 'credit'
    assert txn.amount == money(5000)
    assert wallet.balance == money(0)  # nothing credited before payment

    body = paystack.last_body('transaction/initialize')
    assert body['amount'] == 500000
    assert body['email'] == 'ada@example.com'
    assert body['currency'] == 'NGN'
    assert body['callback_url'] == 'https://shop.test/cb'
    assert body['metadata']['wallet_id'] == str(wallet.pk)
    assert body['metadata']['order'] == 7
    assert result['authorization_url'] == INIT_RESPONSE['authorization_url']
    assert result['access_code'] == 'abc'
    assert result['public_key'].startswith('pk_test_')


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_BEARER='customer', WALLET_DEPOSIT_FEE_GROSS_UP=False)
def test_customer_bearer_charges_amount_plus_fee(service, paystack, wallet):
    result = init(service, paystack, wallet, 10000)
    assert paystack.last_body('transaction/initialize')['amount'] == 1025000
    assert result['charge_amount'] == '10250.00'
    assert result['fee_breakdown']['fee_amount'] == '250.00'


def test_initialize_failure_marks_failed(service, paystack, wallet):
    paystack.error('POST', 'transaction/initialize', 'Invalid key', status=401)
    with pytest.raises(PaystackAPIError):
        service.initialize_deposit(wallet, 1000)
    assert Transaction.objects.get(wallet=wallet).status == 'failed'


def test_initialize_validations(service, paystack, wallet):
    with pytest.raises(InvalidAmount):
        service.initialize_deposit(wallet, 10)          # under WALLET_MINIMUM_DEPOSIT_AMOUNT (50)
    with override_settings(WALLET_MAXIMUM_TRANSACTION_AMOUNT=1000):
        with pytest.raises(Exception):
            service.initialize_deposit(wallet, 5000)
    init(service, paystack, wallet, 1000, reference='ORDER-12345')
    with pytest.raises(DuplicateReference):
        service.initialize_deposit(wallet, 1000, reference='ORDER-12345')
    with override_settings(WALLET_ENABLE_DEPOSITS=False):
        with pytest.raises(FeatureDisabled):
            service.initialize_deposit(wallet, 1000)
    wallet.lock()
    with pytest.raises(WalletLocked):
        service.initialize_deposit(wallet, 1000)


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

def test_charge_success_credits_once(service, paystack, wallet):
    reference = init(service, paystack, wallet, 5000)['reference']
    data = charge_data(reference, 500000)
    service.process_charge(data)
    service.process_charge(data)            # duplicate webhook
    wallet.refresh_from_db()
    assert wallet.balance == money(5000)
    txn = Transaction.objects.get(reference=reference)
    assert txn.status == 'success'
    assert txn.total_amount == money(5000)
    assert txn.balance_after == money(5000)
    assert txn.payment_method == 'card'
    assert txn.completed_at is not None


def test_verify_after_webhook_does_not_double_credit(service, paystack, wallet):
    reference = init(service, paystack, wallet, 5000)['reference']
    service.process_charge(charge_data(reference, 500000))
    txn = service.verify_deposit(reference)       # already final -> no Paystack call
    assert txn.is_successful
    assert not paystack.calls(f'transaction/verify/{reference}')
    wallet.refresh_from_db()
    assert wallet.balance == money(5000)


def test_verify_deposit_calls_paystack(service, paystack, wallet):
    reference = init(service, paystack, wallet, 2000)['reference']
    paystack.add('GET', f'transaction/verify/{reference}', charge_data(reference, 200000))
    txn = service.verify_deposit(reference)
    assert txn.is_successful
    wallet.refresh_from_db()
    assert wallet.balance == money(2000)


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_BEARER='merchant')
def test_merchant_bearer_credits_net(service, paystack, wallet):
    reference = init(service, paystack, wallet, 10000)['reference']
    service.process_charge(charge_data(reference, 1000000))
    wallet.refresh_from_db()
    assert wallet.balance == money('9750.00')
    txn = Transaction.objects.get(reference=reference)
    assert txn.fees == money(250)
    assert FeeHistory.objects.filter(transaction=txn).exists()


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_BEARER='customer')
def test_customer_bearer_credits_requested_amount(service, paystack, wallet):
    result = init(service, paystack, wallet, 10000)
    paid_kobo = int(Decimal(result['charge_amount']) * 100)
    service.process_charge(charge_data(result['reference'], paid_kobo))
    wallet.refresh_from_db()
    assert wallet.balance == money(10000)
    txn = Transaction.objects.get(reference=result['reference'])
    assert txn.fees.amount == Decimal(result['charge_amount']) - 10000


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_BEARER='platform')
def test_platform_bearer_credits_everything(service, paystack, wallet):
    reference = init(service, paystack, wallet, 10000)['reference']
    service.process_charge(charge_data(reference, 1000000))
    wallet.refresh_from_db()
    assert wallet.balance == money(10000)
    assert Transaction.objects.get(reference=reference).fees == money(250)


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_BEARER='merchant')
def test_international_card_is_priced_on_actual_card(service, paystack, wallet):
    reference = init(service, paystack, wallet, 10000)['reference']
    data = charge_data(reference, 1000000)
    data['authorization']['country_code'] = 'US'
    service.process_charge(data)
    wallet.refresh_from_db()
    assert wallet.balance == money('9510.00')     # 3.9% + 100


@override_settings(WALLET_ENABLE_FEES=True, WALLET_DEPOSIT_FEE_BEARER='customer', WALLET_DEPOSIT_FEE_GROSS_UP=False)
def test_underpayment_is_credited_from_what_was_actually_paid(service, paystack, wallet):
    reference = init(service, paystack, wallet, 10000)['reference']
    service.process_charge(charge_data(reference, 500000))    # customer only paid 5,000
    wallet.refresh_from_db()
    assert wallet.balance == money('4825.00')                 # 5,000 - (1.5% + 100)


def test_currency_mismatch_is_flagged_not_credited(service, paystack, wallet):
    reference = init(service, paystack, wallet, 50)['reference']
    txn = service.process_charge(charge_data(reference, 5000, currency='USD'))
    assert txn.status == 'failed'
    assert 'Currency mismatch' in txn.failed_reason
    wallet.refresh_from_db()
    assert wallet.balance == money(0)


@pytest.mark.parametrize('status', ['failed', 'reversed'])
def test_failed_charge(service, paystack, wallet, status):
    reference = init(service, paystack, wallet, 5000)['reference']
    txn = service.process_charge(charge_data(reference, 500000, status=status))
    assert txn.status == 'failed'
    assert txn.failed_reason == 'Declined'


def test_recent_abandoned_charge_stays_pending_old_one_fails(service, paystack, wallet):
    reference = init(service, paystack, wallet, 5000)['reference']
    assert service.process_charge(charge_data(reference, 500000, status='abandoned')).status == 'pending'
    Transaction.objects.filter(reference=reference).update(created_at=timezone.now() - timedelta(days=2))
    assert service.process_charge(charge_data(reference, 500000, status='abandoned')).status == 'failed'


def test_pending_charge_keeps_waiting(service, paystack, wallet):
    reference = init(service, paystack, wallet, 5000)['reference']
    assert service.process_charge(charge_data(reference, 500000, status='ongoing')).status == 'pending'


def test_foreign_charge_is_ignored(service, wallet):
    assert service.process_charge(charge_data('SOME-OTHER-CHECKOUT', 100000)) is None
    assert service.process_charge({}) is None
    assert Transaction.objects.count() == 0


def test_charge_for_non_deposit_reference_is_ignored(service, funded_wallet):
    debit = service.debit_wallet(funded_wallet, 100)
    assert service.process_charge(charge_data(debit.reference, 10000)) is None
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(99900)


# ---------------------------------------------------------------------------
# Dedicated virtual accounts
# ---------------------------------------------------------------------------

@override_settings(WALLET_ENABLE_FEES=True)
def test_dva_transfer_creates_and_credits_deposit(service, wallet):
    wallet.paystack_customer_code = 'CUS_ada'
    wallet.dedicated_account_number = '9930000001'
    wallet.save()
    data = charge_data('DVA-REF-1', 2000000, channel='dedicated_nuban',
                       customer={'customer_code': 'CUS_ada', 'email': 'ada@example.com'},
                       authorization={'channel': 'dedicated_nuban', 'sender_name': 'JOHN DOE',
                                      'sender_bank': 'GTBank', 'receiver_bank_account_number': '9930000001',
                                      'reusable': False})
    txn = service.process_charge(data)
    service.process_charge(data)
    wallet.refresh_from_db()
    assert txn.payment_method == 'dva'
    assert txn.metadata['sender_name'] == 'JOHN DOE'
    assert wallet.balance == money('19800.00')             # 1% (under the 300 cap), borne by wallet (DVA default)
    assert Transaction.objects.filter(reference='DVA-REF-1').count() == 1


def test_dva_transfer_matched_by_account_number(service, wallet):
    wallet.dedicated_account_number = '9930000009'
    wallet.save()
    data = charge_data('DVA-REF-2', 100000, channel='dedicated_nuban', customer={'customer_code': 'CUS_unknown'},
                       authorization={'receiver_bank_account_number': '9930000009'})
    assert service.process_charge(data).is_successful
    wallet.refresh_from_db()
    assert wallet.balance == money(1000)


def test_dva_transfer_to_locked_wallet_is_still_credited(service, wallet):
    wallet.paystack_customer_code = 'CUS_ada'
    wallet.save()
    wallet.lock('review')
    service.process_charge(charge_data('DVA-REF-3', 100000, channel='dedicated_nuban',
                                       customer={'customer_code': 'CUS_ada'}, authorization={}))
    wallet.refresh_from_db()
    assert wallet.balance == money(1000)


def test_unmatched_dva_transfer_is_ignored(service, wallet):
    assert service.process_charge(charge_data('DVA-REF-4', 100000, channel='dedicated_nuban',
                                              customer={'customer_code': 'CUS_nobody'}, authorization={})) is None


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def test_reusable_card_is_saved_once(service, paystack, wallet):
    first = init(service, paystack, wallet, 1000)['reference']
    second = init(service, paystack, wallet, 1000)['reference']
    service.process_charge(charge_data(first, 100000))
    data = charge_data(second, 100000)
    data['authorization']['authorization_code'] = 'AUTH_rotated'   # same card (signature), new auth code
    service.process_charge(data)
    cards = Card.objects.filter(wallet=wallet)
    assert cards.count() == 1
    card = cards.get()
    assert card.paystack_authorization_code == 'AUTH_rotated'
    assert card.is_default and card.card_type == 'visa' and card.last_four == '4081'
    assert Transaction.objects.get(reference=first).card == card


def test_non_reusable_card_not_saved(service, paystack, wallet):
    reference = init(service, paystack, wallet, 1000)['reference']
    data = charge_data(reference, 100000)
    data['authorization']['reusable'] = False
    service.process_charge(data)
    assert not Card.objects.exists()


@override_settings(WALLET_SAVE_CARDS=False)
def test_card_saving_can_be_disabled(service, paystack, wallet):
    reference = init(service, paystack, wallet, 1000)['reference']
    service.process_charge(charge_data(reference, 100000))
    assert not Card.objects.exists()


def test_charge_saved_card_success(service, paystack, card):
    paystack.add('POST', 'transaction/charge_authorization', None)
    reference = 'CARD-TOPUP-1'
    paystack.rsps.replace('POST', 'https://api.paystack.co/transaction/charge_authorization',
                          json={'status': True, 'data': charge_data(reference, 300000)})
    txn = service.charge_card(card, 3000, reference=reference)
    body = paystack.last_body('transaction/charge_authorization')
    assert body['authorization_code'] == 'AUTH_abc123'
    assert body['amount'] == 300000
    assert txn.is_successful and txn.card == card
    card.wallet.refresh_from_db()
    assert card.wallet.balance == money(3000)


def test_charge_saved_card_needs_more_steps(service, paystack, card):
    paystack.add('POST', 'transaction/charge_authorization', {'reference': 'CHG-X', 'status': 'send_otp'})
    txn = service.charge_card(card, 3000, reference='CARD-TOPUP-2')
    assert txn.status == 'pending'


def test_charge_saved_card_declined(service, paystack, card):
    paystack.error('POST', 'transaction/charge_authorization', 'Insufficient funds on card')
    with pytest.raises(PaystackAPIError):
        service.charge_card(card, 3000)
    assert Transaction.objects.get(card=card).status == 'failed'


def test_charge_saved_card_unknown_outcome_stays_pending(service, paystack, card):
    paystack.add('POST', 'transaction/charge_authorization', status=504, body={'status': False})
    txn = service.charge_card(card, 3000)
    assert txn.status == 'pending'
    assert txn.metadata['needs_reconciliation'] is True


def test_charge_rejects_bad_cards(service, card, other_wallet):
    card.expiry_year = '2001'
    card.save()
    with pytest.raises(CardError):
        service.charge_card(card, 1000)
    card.expiry_year = '2099'
    card.is_active = False
    card.save()
    with pytest.raises(CardError):
        service.charge_card(card, 1000)
    with override_settings(WALLET_ENABLE_CARDS=False):
        with pytest.raises(FeatureDisabled):
            service.charge_card(card, 1000)


def test_remove_card_revokes_authorization(service, paystack, card):
    paystack.add('POST', 'customer/deactivate_authorization', {})
    service.remove_card(card)
    assert paystack.last_body('customer/deactivate_authorization') == {'authorization_code': 'AUTH_abc123'}
    card.refresh_from_db()
    assert not card.is_active


# ---------------------------------------------------------------------------
# Cancellation, reconciliation, signals
# ---------------------------------------------------------------------------

def test_cancel_pending_deposit(service, paystack, wallet):
    reference = init(service, paystack, wallet, 1000)['reference']
    txn = service.cancel_deposit(Transaction.objects.get(reference=reference))
    assert txn.status == 'cancelled'


def test_reconcile_pending_deposits(paystack, wallet):
    service = DepositService()
    paystack.add('POST', 'transaction/initialize', INIT_RESPONSE)
    paid = service.initialize_deposit(wallet, 1000)['reference']
    paystack.add('POST', 'transaction/initialize', INIT_RESPONSE)
    lost = service.initialize_deposit(wallet, 1000)['reference']
    Transaction.objects.update(created_at=timezone.now() - timedelta(days=2))
    paystack.add('GET', f'transaction/verify/{paid}', charge_data(paid, 100000))
    paystack.error('GET', f'transaction/verify/{lost}', 'Transaction reference not found')

    assert service.reconcile_pending_deposits(older_than_minutes=5) == 2
    assert Transaction.objects.get(reference=paid).status == 'success'
    assert Transaction.objects.get(reference=lost).status == 'cancelled'


def test_signals_fire_after_commit(service, paystack, wallet, django_capture_on_commit_callbacks):
    completed, failed = [], []
    deposit_completed.connect(lambda **kw: completed.append(kw['transaction'].reference), weak=False,
                              dispatch_uid='t-dc')
    deposit_failed.connect(lambda **kw: failed.append(kw['reason']), weak=False, dispatch_uid='t-df')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            ok = init(service, paystack, wallet, 1000)['reference']
            bad = init(service, paystack, wallet, 1000)['reference']
            service.process_charge(charge_data(ok, 100000))
            service.process_charge(charge_data(bad, 100000, status='failed'))
    finally:
        deposit_completed.disconnect(dispatch_uid='t-dc')
        deposit_failed.disconnect(dispatch_uid='t-df')
    assert completed == [ok]
    assert failed == ['Declined']
