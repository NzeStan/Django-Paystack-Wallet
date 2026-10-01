import hashlib
import hmac
import json

import pytest
from django.utils.crypto import get_random_string
import responses as responses_lib
from django.test import Client, override_settings

from tests.conftest import charge_data, money, webhook_request
from wallet.exceptions import BankAccountError, FeatureDisabled
from wallet.models import Bank, BankAccount, Transaction, WebhookDeliveryAttempt, WebhookEndpoint, WebhookEvent
from wallet.services.bank_account_service import BankAccountService
from wallet.services.webhook_service import WebhookService
from wallet.signals import customer_identification, dispute_event, paystack_webhook_received

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def pending_deposit(service, paystack, wallet):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = service.initialize_deposit(wallet, 5000)['reference']
    return Transaction.objects.get(reference=reference)


# ---------------------------------------------------------------------------
# Receiving webhooks
# ---------------------------------------------------------------------------

def test_valid_webhook_credits_wallet(client, pending_deposit):
    response = webhook_request(client, {'event': 'charge.success',
                                        'data': charge_data(pending_deposit.reference, 500000)})
    assert response.status_code == 200
    assert response.json()['duplicate'] is False
    pending_deposit.wallet.refresh_from_db()
    assert pending_deposit.wallet.balance == money(5000)
    event = WebhookEvent.objects.get()
    assert event.processed and event.transaction == pending_deposit


def test_duplicate_webhook_is_ignored(client, pending_deposit):
    payload = {'event': 'charge.success', 'data': charge_data(pending_deposit.reference, 500000)}
    webhook_request(client, payload)
    response = webhook_request(client, payload)
    assert response.json()['duplicate'] is True
    assert WebhookEvent.objects.count() == 1
    pending_deposit.wallet.refresh_from_db()
    assert pending_deposit.wallet.balance == money(5000)


def test_bad_or_missing_signature(client, pending_deposit):
    payload = {'event': 'charge.success', 'data': charge_data(pending_deposit.reference, 500000)}
    assert webhook_request(client, payload, secret='sk_test_wrong-dummy-key-for-tests').status_code == 401
    response = client.post('/wallet/webhook/', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 401
    assert not WebhookEvent.objects.exists()
    pending_deposit.wallet.refresh_from_db()
    assert pending_deposit.wallet.balance == money(0)


def test_malformed_payloads(client):
    from wallet.paystack.client import compute_signature
    for body in (b'not json', b'{"data": {}}', b'[]'):
        response = client.post('/wallet/webhook/', data=body, content_type='application/json',
                               HTTP_X_PAYSTACK_SIGNATURE=compute_signature(body))
        assert response.status_code == 400


@override_settings(WALLET_WEBHOOK_VERIFY_IP=True)
def test_ip_allowlist(client, pending_deposit):
    payload = {'event': 'charge.success', 'data': charge_data(pending_deposit.reference, 500000)}
    assert webhook_request(client, payload, REMOTE_ADDR='10.0.0.1').status_code == 401
    assert webhook_request(client, payload, REMOTE_ADDR='52.31.139.75').status_code == 200


def test_processing_error_is_stored_and_replayable(client, pending_deposit, monkeypatch):
    from wallet.services.deposit_service import DepositService

    def explode(*args, **kwargs):
        raise RuntimeError('database hiccup')
    monkeypatch.setattr(DepositService, 'process_charge', explode)
    response = webhook_request(client, {'event': 'charge.success',
                                        'data': charge_data(pending_deposit.reference, 500000)})
    assert response.status_code == 200
    event = WebhookEvent.objects.get()
    assert not event.processed and 'database hiccup' in event.processing_error

    monkeypatch.undo()
    assert WebhookService().reprocess_webhook_event(event.pk)
    event.refresh_from_db()
    assert event.processed and event.processing_attempts == 2
    pending_deposit.wallet.refresh_from_db()
    assert pending_deposit.wallet.balance == money(5000)


def test_unhandled_events_reach_your_code(client, django_capture_on_commit_callbacks):
    received = []
    paystack_webhook_received.connect(lambda **kw: received.append((kw['event'], kw['handled'])), weak=False,
                                      dispatch_uid='pwr')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            webhook_request(client, {'event': 'subscription.create', 'data': {'subscription_code': 'SUB_1'}})
    finally:
        paystack_webhook_received.disconnect(dispatch_uid='pwr')
    assert received == [('subscription.create', False)]
    assert WebhookEvent.objects.get().processed


def test_transfer_webhooks(client, service, paystack, funded_wallet, bank_account):
    paystack.add('POST', 'transfer', {'reference': 'wdr-hook-reference-01', 'status': 'pending',
                                      'transfer_code': 'TRF_1'})
    txn, _ = service.withdraw_to_bank(funded_wallet, 1000, bank_account, reference='wdr-hook-reference-01')
    webhook_request(client, {'event': 'transfer.failed', 'data': {'reference': txn.reference,
                                                                   'transfer_code': 'TRF_1', 'reason': 'Bank down'}})
    txn.refresh_from_db()
    funded_wallet.refresh_from_db()
    assert txn.status == 'failed' and txn.failed_reason == 'Bank down'
    assert funded_wallet.balance == money(100000)


def test_dispute_signal(client, pending_deposit, django_capture_on_commit_callbacks):
    seen = []
    dispute_event.connect(lambda **kw: seen.append((kw['event'], kw['transaction'])), weak=False, dispatch_uid='d')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            webhook_request(client, {'event': 'charge.dispute.create',
                                     'data': {'id': 1, 'transaction': {'reference': pending_deposit.reference}}})
    finally:
        dispute_event.disconnect(dispatch_uid='d')
    assert seen == [('charge.dispute.create', pending_deposit)]


def test_charge_webhooks_processed_async_with_celery(client, pending_deposit, settings,
                                                     django_capture_on_commit_callbacks):
    settings.WALLET_USE_CELERY = True
    from wallet import tasks
    calls = []
    original = tasks.process_webhook_event_task.delay
    task = tasks.process_webhook_event_task
    tasks.process_webhook_event_task.delay = lambda event_id: calls.append(event_id) or task(event_id)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            webhook_request(client, {'event': 'charge.success',
                                     'data': charge_data(pending_deposit.reference, 500000)})
    finally:
        tasks.process_webhook_event_task.delay = original
    assert len(calls) == 1
    pending_deposit.wallet.refresh_from_db()
    assert pending_deposit.wallet.balance == money(5000)


# ---------------------------------------------------------------------------
# Forwarding to your own endpoints
# ---------------------------------------------------------------------------

@override_settings(WALLET_ENABLE_WEBHOOK_FORWARDING=True)
def test_forwarding_is_signed_and_filtered(client, pending_deposit, other_wallet):
    signing_secret = get_random_string(24)
    WebhookEndpoint.objects.create(name='all', url='https://hooks.test/all', secret=signing_secret)
    WebhookEndpoint.objects.create(name='only-transfers', url='https://hooks.test/transfers',
                                   event_types=['transfer.success'])
    scoped = WebhookEndpoint.objects.create(name='other-wallet', url='https://hooks.test/other')
    scoped.wallets.add(other_wallet)

    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add('POST', 'https://hooks.test/all', json={}, status=200)
        webhook_request(client, {'event': 'charge.success', 'data': charge_data(pending_deposit.reference, 500000)})
        assert len(rsps.calls) == 1
        request = rsps.calls[0].request
        expected = hmac.new(signing_secret.encode(), request.body, hashlib.sha512).hexdigest()
        assert request.headers['X-Wallet-Signature'] == expected
        assert request.headers['X-Wallet-Event'] == 'charge.success'
    attempt = WebhookDeliveryAttempt.objects.get()
    assert attempt.is_success and 'X-Wallet-Signature' not in attempt.request_data['headers']


@override_settings(WALLET_ENABLE_WEBHOOK_FORWARDING=True)
def test_failed_deliveries_are_retried_up_to_limit(client, pending_deposit):
    WebhookEndpoint.objects.create(name='flaky', url='https://hooks.test/flaky', retry_count=2)
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add('POST', 'https://hooks.test/flaky', json={}, status=500)
        webhook_request(client, {'event': 'charge.success', 'data': charge_data(pending_deposit.reference, 500000)})
        service = WebhookService()
        assert service.retry_all_failed_deliveries() == 1
        assert service.retry_all_failed_deliveries() == 0     # retry_count reached
    assert WebhookDeliveryAttempt.objects.count() == 2
    assert not WebhookDeliveryAttempt.objects.filter(is_success=True).exists()


def test_forwarding_off_by_default(client, pending_deposit):
    WebhookEndpoint.objects.create(name='all', url='https://hooks.test/all')
    webhook_request(client, {'event': 'charge.success', 'data': charge_data(pending_deposit.reference, 500000)})
    assert not WebhookDeliveryAttempt.objects.exists()


# ---------------------------------------------------------------------------
# Customers, identity and dedicated accounts
# ---------------------------------------------------------------------------

def test_dedicated_account_assignment_webhook(client, wallet):
    webhook_request(client, {'event': 'dedicatedaccount.assign.success', 'data': {
        'customer': {'customer_code': 'CUS_new', 'id': 3, 'email': 'ada@example.com'},
        'dedicated_account': {'id': 42, 'account_number': '9930000042', 'account_name': 'ADA OBI', 'active': True,
                              'bank': {'name': 'Wema Bank', 'slug': 'wema-bank'}},
    }})
    wallet.refresh_from_db()
    assert wallet.paystack_customer_code == 'CUS_new'
    assert wallet.dedicated_account_number == '9930000042'
    assert wallet.dedicated_account_bank == 'Wema Bank'


def test_identification_success_creates_dva(client, paystack, wallet, settings, django_capture_on_commit_callbacks):
    settings.WALLET_AUTO_CREATE_DEDICATED_ACCOUNT = True
    wallet.paystack_customer_code = 'CUS_ada'
    wallet.save()
    paystack.add('POST', 'dedicated_account', {'id': 5, 'account_number': '9930000005', 'account_name': 'ADA',
                                               'bank': {'name': 'Test Bank', 'slug': 'test-bank'}})
    seen = []
    customer_identification.connect(lambda **kw: seen.append(kw['success']), weak=False, dispatch_uid='ci')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            webhook_request(client, {'event': 'customeridentification.success',
                                     'data': {'customer_code': 'CUS_ada', 'email': 'ada@example.com'}})
    finally:
        customer_identification.disconnect(dispatch_uid='ci')
    wallet.refresh_from_db()
    assert wallet.customer_identified and wallet.dedicated_account_number == '9930000005'
    assert seen == [True]


def test_customer_service_calls(service, paystack, wallet):
    paystack.add('POST', 'customer', {'customer_code': 'CUS_ada', 'id': 1})
    assert service.ensure_customer(wallet) == 'CUS_ada'
    assert service.ensure_customer(wallet) == 'CUS_ada'
    assert len(paystack.calls('customer', 'POST')) == 1

    paystack.add('POST', 'customer/CUS_ada/identification', {})
    service.validate_customer(wallet, 'Ada', 'Obi', bvn='22222222222', bank_code='058', account_number='0123456789')
    assert paystack.last_body('customer/CUS_ada/identification')['bvn'] == '22222222222'

    paystack.add('POST', 'customer/set_risk_action', {})
    service.set_risk_action(wallet, 'deny')
    assert paystack.last_body('customer/set_risk_action') == {'customer': 'CUS_ada', 'risk_action': 'deny'}

    paystack.add('POST', 'dedicated_account/assign', {})
    service.assign_dedicated_account(wallet, phone='+2348031234567', preferred_bank='wema-bank')
    assert paystack.last_body('dedicated_account/assign')['email'] == 'ada@example.com'


def test_dedicated_account_lifecycle(service, paystack, wallet):
    wallet.paystack_customer_code = 'CUS_ada'
    wallet.save()
    paystack.add('POST', 'dedicated_account', {'id': 7, 'account_number': '9930000007', 'account_name': 'ADA',
                                               'active': True, 'bank': {'name': 'Wema', 'slug': 'wema-bank'}})
    service.create_dedicated_account(wallet)
    assert service.get_dedicated_account(wallet)['account_number'] == '9930000007'

    paystack.add('GET', 'dedicated_account/requery', {})
    service.requery_dedicated_account(wallet)
    assert 'provider_slug=wema-bank' in paystack.calls('dedicated_account/requery')[0].request.url

    paystack.add('DELETE', 'dedicated_account/7', {'active': False})
    service.deactivate_dedicated_account(wallet)
    assert not wallet.dedicated_account_active

    with override_settings(WALLET_ENABLE_DEDICATED_ACCOUNTS=False):
        with pytest.raises(FeatureDisabled):
            service.create_dedicated_account(wallet)


# ---------------------------------------------------------------------------
# Banks & bank accounts
# ---------------------------------------------------------------------------

def test_sync_banks_follows_cursor(paystack):
    paystack.add('GET', 'bank', [{'name': 'Access Bank', 'code': '044', 'currency': 'NGN', 'type': 'nuban'}],
                 meta={'next': 'cursor2'})
    paystack.add('GET', 'bank', [{'name': 'GTBank', 'code': '058', 'currency': 'NGN', 'type': 'nuban'}],
                 meta={'next': None})
    created, updated, errors = BankAccountService().sync_banks()
    assert (created, updated, errors) == (2, 0, 0)
    assert 'next=cursor2' in paystack.calls('bank')[1].request.url
    paystack.add('GET', 'bank', [{'name': 'Access Bank Plc', 'code': '044', 'currency': 'NGN', 'type': 'nuban'}],
                 meta={})
    assert BankAccountService().sync_banks() == (0, 1, 0)
    assert Bank.objects.get(code='044').name == 'Access Bank Plc'


def test_add_bank_account_uses_verified_name(service, paystack, wallet, bank):
    paystack.add('GET', 'bank/resolve', {'account_number': '0123456789', 'account_name': 'ADAEZE OBI', 'bank_id': 9})
    paystack.add('POST', 'transferrecipient', {'recipient_code': 'RCP_x', 'id': 1, 'details': {}})
    account = service.add_bank_account(wallet, '058', '0123456789', account_name='Somebody Else')
    assert account.account_name == 'ADAEZE OBI'
    assert account.is_verified and account.is_default
    assert account.paystack_recipient_code == 'RCP_x'
    assert paystack.last_body('transferrecipient')['type'] == 'nuban'

    # Adding the same account again re-activates rather than duplicating
    account.remove()
    paystack.add('GET', 'bank/resolve', {'account_number': '0123456789', 'account_name': 'ADAEZE OBI'})
    again = service.add_bank_account(wallet, '058', '0123456789')
    assert again.pk == account.pk and again.is_active
    assert BankAccount.objects.count() == 1


def test_add_bank_account_errors(service, paystack, wallet, bank):
    with pytest.raises(BankAccountError):
        service.add_bank_account(wallet, '999', '0123456789')
    paystack.error('GET', 'bank/resolve', 'Could not resolve account name')
    with pytest.raises(BankAccountError):
        service.add_bank_account(wallet, '058', '0000000000')


def test_recipient_failure_does_not_block_saving(service, paystack, wallet, bank):
    paystack.add('GET', 'bank/resolve', {'account_name': 'ADA OBI'})
    paystack.error('POST', 'transferrecipient', 'Account number is invalid')
    account = service.add_bank_account(wallet, '058', '0123456789')
    assert account.pk and account.paystack_recipient_code is None


def test_remove_bank_account_deletes_recipient(service, paystack, bank_account):
    paystack.add('DELETE', 'transferrecipient/RCP_test123', {})
    service.remove_bank_account(bank_account, delete_recipient=True)
    assert not bank_account.is_active
    assert paystack.calls('transferrecipient/RCP_test123', 'DELETE')
