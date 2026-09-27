"""Rate limiting, idempotency keys, audit trail and data retention."""
import json
import logging
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from tests.conftest import money
from wallet.models import IdempotencyRecord, Transaction, WebhookDeliveryAttempt, WebhookEndpoint, WebhookEvent
from wallet.services.transaction_service import TransactionService
from wallet.services.webhook_service import WebhookService

pytestmark = pytest.mark.django_db

API = '/wallet/api'


def transfer(client, key=None, amount='100', recipient='bola'):
    headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
    return client.post(f'{API}/wallets/me/transfer/', {'recipient': recipient, 'amount': amount},
                       format='json', **headers)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_retry_with_same_key_moves_money_once(api_client, funded_wallet, other_wallet):
    first = transfer(api_client, key='order-1')
    second = transfer(api_client, key='order-1')
    assert first.status_code == second.status_code == 201
    assert second['Idempotent-Replayed'] == 'true'
    assert second.json() == first.json()
    other_wallet.refresh_from_db()
    assert other_wallet.balance == money(100)
    assert Transaction.objects.filter(transaction_type='transfer', direction='debit').count() == 1


def test_different_keys_are_different_requests(api_client, funded_wallet, other_wallet):
    transfer(api_client, key='a')
    transfer(api_client, key='b')
    other_wallet.refresh_from_db()
    assert other_wallet.balance == money(200)


def test_no_key_means_no_protection(api_client, funded_wallet, other_wallet):
    transfer(api_client)
    transfer(api_client)
    other_wallet.refresh_from_db()
    assert other_wallet.balance == money(200)


def test_key_reused_with_different_body_is_rejected(api_client, funded_wallet, other_wallet):
    transfer(api_client, key='k1', amount='100')
    response = transfer(api_client, key='k1', amount='900')
    assert response.status_code == 422 and response.json()['code'] == 'idempotency_key_reused'


def test_in_progress_request_conflicts(api_client, user, funded_wallet, other_wallet):
    import hashlib
    endpoint = f'POST {API}/wallets/me/transfer/'
    payload = json.dumps({'recipient': 'bola', 'amount': '100'}, sort_keys=True)
    IdempotencyRecord.objects.create(user=user, key='busy', endpoint=endpoint,
                                     request_hash=hashlib.sha256(f"{endpoint}\n{payload}".encode()).hexdigest())
    response = transfer(api_client, key='busy')
    assert response.status_code == 409 and response.json()['code'] == 'idempotency_in_progress'


def test_business_errors_are_replayed_but_server_errors_are_not(api_client, funded_wallet, other_wallet,
                                                                  monkeypatch):
    poor = transfer(api_client, key='too-much', amount='999999')
    assert poor.status_code == 400
    assert transfer(api_client, key='too-much', amount='999999')['Idempotent-Replayed'] == 'true'

    from wallet.services.wallet_service import WalletService

    def crash(*args, **kwargs):
        raise RuntimeError('db down')
    monkeypatch.setattr(WalletService, 'transfer', crash)
    client = APIClient(raise_request_exception=False)
    client.force_authenticate(funded_wallet.user)
    assert transfer(client, key='retry-me').status_code == 500
    assert not IdempotencyRecord.objects.filter(key='retry-me').exists()   # safe to retry
    monkeypatch.undo()
    assert transfer(api_client, key='retry-me').status_code == 201


def test_keys_are_per_user(api_client, funded_wallet, other_wallet, service):
    service.credit_wallet(other_wallet, 500)
    other = APIClient()
    other.force_authenticate(other_wallet.user)
    assert transfer(api_client, key='same').status_code == 201
    response = transfer(other, key='same', recipient='ada')
    assert response.status_code == 201 and 'Idempotent-Replayed' not in response


def test_expired_keys_can_be_reused(api_client, funded_wallet, other_wallet, settings):
    transfer(api_client, key='old')
    IdempotencyRecord.objects.update(created_at=timezone.now() - timedelta(hours=25))
    assert 'Idempotent-Replayed' not in transfer(api_client, key='old')
    other_wallet.refresh_from_db()
    assert other_wallet.balance == money(200)


@override_settings(WALLET_REQUIRE_IDEMPOTENCY_KEY=True)
def test_keys_can_be_required(api_client, funded_wallet, other_wallet):
    response = transfer(api_client)
    assert response.status_code == 400 and response.json()['code'] == 'idempotency_key_required'
    assert transfer(api_client, key='x').status_code == 201
    assert api_client.get(f'{API}/wallets/me/balance/').status_code == 200   # reads unaffected


def test_idempotency_on_withdrawals_and_deposits(api_client, paystack, funded_wallet, bank_account):
    paystack.add('POST', 'transfer', {'status': 'pending', 'transfer_code': 'TRF_i'})
    body = {'amount': '1000'}
    first = api_client.post(f'{API}/wallets/me/withdraw/', body, format='json', HTTP_IDEMPOTENCY_KEY='w1')
    second = api_client.post(f'{API}/wallets/me/withdraw/', body, format='json', HTTP_IDEMPOTENCY_KEY='w1')
    assert first.status_code == second.status_code == 202
    assert len(paystack.calls('transfer', 'POST')) == 1

    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    d1 = api_client.post(f'{API}/wallets/me/deposit/', body, format='json', HTTP_IDEMPOTENCY_KEY='d1')
    d2 = api_client.post(f'{API}/wallets/me/deposit/', body, format='json', HTTP_IDEMPOTENCY_KEY='d1')
    assert d1.json()['reference'] == d2.json()['reference']
    assert len(paystack.calls('transaction/initialize')) == 1


def test_invalid_key(api_client, funded_wallet):
    assert transfer(api_client, key='x' * 300).status_code == 400


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

@override_settings(WALLET_THROTTLE_RATES={'lookup': '3/min'})
def test_lookup_is_rate_limited(api_client, wallet, other_wallet):
    for _ in range(3):
        assert api_client.get(f'{API}/wallets/lookup/', {'recipient': 'bola'}).status_code == 200
    response = api_client.get(f'{API}/wallets/lookup/', {'recipient': 'bola'})
    assert response.status_code == 429
    assert int(response['Retry-After']) > 0
    assert api_client.get(f'{API}/wallets/me/').status_code == 200    # other endpoints unaffected


@override_settings(WALLET_THROTTLE_RATES={'money': '2/min'})
def test_money_endpoints_are_rate_limited_per_user(api_client, funded_wallet, other_wallet, service):
    assert transfer(api_client).status_code == 201
    assert transfer(api_client).status_code == 201
    assert transfer(api_client).status_code == 429
    service.credit_wallet(other_wallet, 100)
    other = APIClient()
    other.force_authenticate(other_wallet.user)
    assert transfer(other, recipient='ada', amount='10').status_code == 201   # separate bucket


@override_settings(WALLET_ENABLE_THROTTLING=False, WALLET_THROTTLE_RATES={'lookup': '1/min'})
def test_throttling_can_be_disabled(api_client, wallet, other_wallet):
    for _ in range(3):
        assert api_client.get(f'{API}/wallets/lookup/', {'recipient': 'bola'}).status_code == 200


@override_settings(WALLET_THROTTLE_RATES={'pin': '2/min'})
def test_pin_endpoint_is_rate_limited(api_client, wallet):
    for _ in range(2):
        api_client.post(f'{API}/wallets/me/set-pin/', {'pin': '1', 'confirm_pin': '1'}, format='json')
    assert api_client.post(f'{API}/wallets/me/set-pin/', {'pin': '1', 'confirm_pin': '1'},
                           format='json').status_code == 429


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def test_staff_actions_are_audited(staff_client, staff_user, service, funded_wallet, other_wallet, caplog):
    debit = service.transfer(funded_wallet, other_wallet, 500)
    with caplog.at_level(logging.INFO, logger='wallet.audit'):
        response = staff_client.post(f'{API}/transactions/{debit.pk}/reverse/', {'reason': 'fraud'}, format='json')
    assert response.status_code == 201
    reversal = Transaction.objects.get(pk=response.json()['id'])
    assert reversal.metadata['performed_by'] == str(staff_user.pk)
    record = json.loads(caplog.records[-1].getMessage())
    assert record == {'action': 'transaction.reverse', 'performed_by': str(staff_user.pk),
                      'transaction': debit.reference, 'reason': 'fraud'}


def test_escrow_and_lock_audit(service, funded_wallet, other_wallet, staff_user, caplog):
    payment = service.pay(funded_wallet, 100, merchant_wallet=other_wallet, escrow=True)
    with caplog.at_level(logging.INFO, logger='wallet.audit'):
        service.release_payment(payment, performed_by=funded_wallet.user)
        service.lock_wallet_account(other_wallet, 'review', performed_by=staff_user)
        service.unlock_wallet_account(other_wallet, performed_by=staff_user)
        cancelled = service.pay(funded_wallet, 50, merchant_wallet=other_wallet, escrow=True)
        TransactionService().cancel_transaction(cancelled, 'dispute', performed_by=staff_user)
    actions = [json.loads(r.getMessage())['action'] for r in caplog.records if r.name == 'wallet.audit']
    assert actions == ['escrow.release', 'wallet.lock', 'wallet.unlock', 'escrow.cancel']
    payment.refresh_from_db()
    assert payment.metadata['released_by'] == str(funded_wallet.user_id)


# ---------------------------------------------------------------------------
# Retention & reconciliation at scale
# ---------------------------------------------------------------------------

def test_prune_keeps_recent_unprocessed_and_ledger(funded_wallet, user):
    old = timezone.now() - timedelta(days=100)
    endpoint = WebhookEndpoint.objects.create(name='e', url='https://hooks.test/e')
    processed_old = WebhookEvent.objects.create(event_type='x', payload={}, idempotency_key='1', processed=True)
    unprocessed_old = WebhookEvent.objects.create(event_type='x', payload={}, idempotency_key='2', processed=False)
    recent = WebhookEvent.objects.create(event_type='x', payload={}, idempotency_key='3', processed=True)
    WebhookDeliveryAttempt.objects.create(webhook_event=recent, webhook_endpoint=endpoint)
    WebhookEvent.objects.filter(pk__in=[processed_old.pk, unprocessed_old.pk]).update(created_at=old)
    IdempotencyRecord.objects.create(user=user, key='k', endpoint='e', request_hash='h')
    IdempotencyRecord.objects.update(created_at=old)

    result = WebhookService.prune()
    assert result == {'webhook_events': 1, 'delivery_attempts': 0, 'idempotency_records': 1}
    assert set(WebhookEvent.objects.values_list('idempotency_key', flat=True)) == {'2', '3'}
    assert Transaction.objects.filter(wallet=funded_wallet).exists()
    with override_settings(WALLET_WEBHOOK_RETENTION_DAYS=None):
        assert WebhookService.prune()['webhook_events'] == 0


def test_prune_command_and_task():
    from io import StringIO

    from django.core.management import call_command

    from wallet.tasks import prune_wallet_data_task
    out = StringIO()
    call_command('prune_wallet_data', '--days', '30', stdout=out)
    assert 'Deleted 0 webhook event(s)' in out.getvalue()
    assert prune_wallet_data_task() == {'webhook_events': 0, 'delivery_attempts': 0, 'idempotency_records': 0}


def test_reconciliation_skips_otp_holds_without_starving_the_batch(service, paystack, funded_wallet, bank_account):
    paystack.add('POST', 'transfer', {'status': 'otp', 'transfer_code': 'TRF_otp'})
    otp_txn, _ = service.withdraw_to_bank(funded_wallet, 1000, bank_account)
    paystack.add('POST', 'transfer', status=504, body={'status': False})
    lost_txn, _ = service.withdraw_to_bank(funded_wallet, 1000, bank_account)
    Transaction.objects.filter(pk=otp_txn.pk).update(created_at=timezone.now() - timedelta(hours=2))
    Transaction.objects.filter(pk=lost_txn.pk).update(created_at=timezone.now() - timedelta(hours=1))
    paystack.add('GET', f'transfer/verify/{lost_txn.reference}', {'status': 'success'})

    assert service.reconcile_pending_withdrawals(older_than_minutes=5, limit=1) == 1
    lost_txn.refresh_from_db()
    assert lost_txn.status == 'success'


def test_old_failed_deliveries_are_not_retried(pending_event_with_failed_delivery):
    WebhookDeliveryAttempt.objects.update(created_at=timezone.now() - timedelta(days=10))
    assert WebhookService().retry_all_failed_deliveries() == 0


@pytest.fixture
def pending_event_with_failed_delivery():
    endpoint = WebhookEndpoint.objects.create(name='e', url='https://hooks.test/e', retry_count=5)
    event = WebhookEvent.objects.create(event_type='x', payload={}, idempotency_key='z', processed=True)
    return WebhookDeliveryAttempt.objects.create(webhook_event=event, webhook_endpoint=endpoint, is_success=False)
