"""Secondary paths: tasks, staff tooling, helper modules and less common API branches."""
from types import SimpleNamespace

import pytest
from django.test import override_settings

from tests.conftest import charge_data, fund, webhook_request
from wallet import tasks
from wallet.exceptions import PaystackAPIError, WalletError
from wallet.models import Bank, Settlement, Transaction, WebhookDeliveryAttempt, WebhookEndpoint, WebhookEvent
from wallet.permissions import HasOperationalWallet, IsWalletOwner, IsWebhookEndpointOwner
from wallet.services.webhook_service import WebhookService
from wallet.utils import bank_sync

pytestmark = pytest.mark.django_db

API = '/wallet/api'


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def test_wallet_and_customer_tasks(user, paystack, settings):
    from wallet.models import Wallet
    wallet_id = tasks.create_wallet_for_user_task(user.pk)
    wallet = Wallet.objects.get(pk=wallet_id)

    paystack.add('POST', 'customer', {'customer_code': 'CUS_1', 'id': 1})
    paystack.add('POST', 'dedicated_account', {'id': 3, 'account_number': '9930000003', 'bank': {}})
    assert tasks.setup_paystack_customer_task(str(wallet.pk), True) is True
    wallet.refresh_from_db()
    assert wallet.dedicated_account_number == '9930000003'


def test_customer_task_gives_up_on_rejection_and_retries_otherwise(wallet, paystack, monkeypatch):
    pytest.importorskip('celery')
    paystack.error('POST', 'customer', 'Invalid email')
    assert tasks.setup_paystack_customer_task(str(wallet.pk)) is False

    paystack.add('POST', 'customer', status=503, body={'status': False, 'message': 'down'})
    retried = []

    def fake_retry(exc=None, **kwargs):
        retried.append(exc)
        raise RuntimeError('retry scheduled')
    monkeypatch.setattr(tasks.setup_paystack_customer_task, 'retry', fake_retry)
    with pytest.raises(RuntimeError):
        tasks.setup_paystack_customer_task(str(wallet.pk))
    assert isinstance(retried[0], PaystackAPIError)


def test_webhook_and_settlement_tasks(paystack, funded_wallet, bank_account):
    event = WebhookEvent.objects.create(event_type='subscription.create', payload={'data': {}}, idempotency_key='k')
    assert tasks.process_webhook_event_task(str(event.pk)) is True

    endpoint = WebhookEndpoint.objects.create(name='e', url='https://hooks.test/e')
    import responses as responses_lib
    with responses_lib.RequestsMock() as rsps:
        rsps.add('POST', 'https://hooks.test/e', status=200, json={})
        assert tasks.deliver_webhook_task(str(event.pk), str(endpoint.pk)) is True

    paystack.add('POST', 'transfer', {'status': 'pending', 'transfer_code': 'TRF_z'})
    from wallet.services.settlement_service import SettlementService
    settlement = SettlementService().create_settlement(funded_wallet, bank_account, 1000)
    paystack.add('GET', f'transfer/verify/{settlement.transaction.reference}', {'status': 'success'})
    assert tasks.verify_pending_settlements_task() == 1
    settlement.refresh_from_db()
    assert settlement.status == 'success'
    assert tasks.process_wallet_settlement_schedules_task(str(funded_wallet.pk)) == 0

    paystack.add('POST', 'dedicated_account', {'id': 4, 'account_number': '9930000004', 'bank': {}})
    funded_wallet.paystack_customer_code = 'CUS_x'
    funded_wallet.save()
    assert tasks.create_dedicated_account_task(str(funded_wallet.pk)) is True


def test_sync_banks_task_and_helpers(paystack):
    paystack.add('GET', 'bank', [{'name': 'Opay', 'code': '999992', 'currency': 'NGN', 'type': 'nuban'}], meta={})
    assert tasks.sync_banks_from_paystack_task() == {'created': 1, 'updated': 0, 'errors': 0}
    assert bank_sync.ensure_banks_exist() is True
    assert bank_sync.get_bank_by_code('999992').name == 'Opay'


def test_ensure_banks_exist_when_empty(paystack):
    paystack.error('GET', 'bank', 'nope', status=401)
    assert bank_sync.ensure_banks_exist() is False


@pytest.mark.django_db(transaction=True)
def test_auto_sync_banks_after_migrate(paystack, settings):
    from wallet.apps import sync_banks_on_first_migrate
    settings.WALLET_AUTO_SYNC_BANKS = True
    paystack.add('GET', 'bank', [{'name': 'Kuda', 'code': '50211', 'currency': 'NGN', 'type': 'nuban'}], meta={})
    sync_banks_on_first_migrate(sender=None)
    assert Bank.objects.filter(code='50211').exists()
    sync_banks_on_first_migrate(sender=None)          # banks exist -> no second call
    assert len(paystack.calls('bank')) == 1


@pytest.mark.django_db(transaction=True)
def test_wallet_creation_is_queued_with_celery(django_user_model, settings, monkeypatch):
    settings.WALLET_USE_CELERY = True
    queued = []
    monkeypatch.setattr(tasks.create_wallet_for_user_task, 'delay', lambda pk: queued.append(pk))
    user = django_user_model.objects.create_user(username='q', email='q@example.com')
    assert queued == [user.pk]


# ---------------------------------------------------------------------------
# Webhook tooling
# ---------------------------------------------------------------------------

def test_webhook_service_helpers(wallet):
    service = WebhookService()
    endpoint = service.register_webhook_endpoint('n', 'https://hooks.test/n', wallets=[wallet], secret='s',
                                                 event_types=['charge.success'])
    assert endpoint.accepts('charge.success') and not endpoint.accepts('transfer.success')
    assert list(endpoint.wallets.all()) == [wallet]
    event = WebhookEvent.objects.create(event_type='charge.success', payload={'data': {}}, idempotency_key='x',
                                        processed=True)
    assert service.get_webhook_event(event.pk) == event
    assert service.get_webhook_event('00000000-0000-0000-0000-000000000000') is None
    assert service.list_webhook_events(event_type='charge.success', processed=True) == [event]


def test_retry_rules(wallet):
    import responses as responses_lib
    service = WebhookService()
    event = WebhookEvent.objects.create(event_type='charge.success', payload={}, idempotency_key='y')
    endpoint = WebhookEndpoint.objects.create(name='n', url='https://hooks.test/r', retry_count=1)
    with responses_lib.RequestsMock() as rsps:
        rsps.add('POST', 'https://hooks.test/r', body=__import__('requests').ConnectionError('refused'))
        attempt = service.forward_webhook_to_endpoint(event, endpoint)
    assert not attempt.is_success and 'refused' in attempt.response_body
    with pytest.raises(WalletError):
        service.retry_failed_webhook_delivery(attempt)            # retry_count exhausted
    attempt.is_success = True
    with pytest.raises(WalletError):
        service.retry_failed_webhook_delivery(attempt)


@override_settings(WALLET_ENABLE_WEBHOOK_FORWARDING=True, WALLET_USE_CELERY=True)
def test_forwarding_is_queued_with_celery(client, service, paystack, wallet, monkeypatch,
                                          django_capture_on_commit_callbacks):
    WebhookEndpoint.objects.create(name='n', url='https://hooks.test/q')
    queued = []
    monkeypatch.setattr(tasks.deliver_webhook_task, 'delay', lambda *args: queued.append(args))
    monkeypatch.setattr(tasks.process_webhook_event_task, 'delay',
                        lambda pk: WebhookService().reprocess_webhook_event(pk))
    with django_capture_on_commit_callbacks(execute=True):
        webhook_request(client, {'event': 'subscription.create', 'data': {}})
    assert len(queued) == 1


def test_staff_webhook_endpoints(staff_client, wallet):
    import responses as responses_lib
    assert staff_client.post(f'{API}/webhook-endpoints/1/test/').status_code == 404
    endpoint = WebhookEndpoint.objects.create(name='n', url='https://hooks.test/s', retry_count=3)
    assert staff_client.post(f'{API}/webhook-endpoints/{endpoint.pk}/test/').status_code == 400   # no events yet
    event = WebhookEvent.objects.create(event_type='charge.success', payload={'data': {}}, idempotency_key='z')
    with responses_lib.RequestsMock() as rsps:
        rsps.add('POST', 'https://hooks.test/s', status=500, json={})
        rsps.add('POST', 'https://hooks.test/s', status=200, json={})
        tested = staff_client.post(f'{API}/webhook-endpoints/{endpoint.pk}/test/')
        assert tested.json()['is_success'] is False
        attempt = WebhookDeliveryAttempt.objects.get()
        retried = staff_client.post(f'{API}/webhook-deliveries/{attempt.pk}/retry/')
        assert retried.json()['is_success'] is True
    assert staff_client.post(f'{API}/webhook-deliveries/{attempt.pk}/retry/').status_code == 400
    reprocessed = staff_client.post(f'{API}/webhook-events/{event.pk}/reprocess/')
    assert reprocessed.status_code == 200
    assert staff_client.get(f'{API}/webhook-events/', {'processed': 'true', 'event_type': 'charge.success'}).json()[
        'count'] == 1


# ---------------------------------------------------------------------------
# API branches
# ---------------------------------------------------------------------------

def test_wallet_history_filters(api_client, service, funded_wallet, other_wallet):
    service.transfer(funded_wallet, other_wallet, 100, description='Groceries')
    params = {'search': 'Groceries', 'start_date': '2000-01-01', 'end_date': '2999-12-31'}
    assert api_client.get(f'{API}/wallets/me/transactions/', params).json()['count'] == 1
    assert api_client.get(f'{API}/transactions/', params).json()['count'] == 1
    assert api_client.get(f'{API}/wallets/me/transactions/', {'start_date': 'garbage'}).status_code == 200
    assert api_client.get(f'{API}/wallets/not-a-uuid/').status_code == 404


def test_wallet_charge_card_and_otp_endpoints(api_client, paystack, card, funded_wallet, bank_account):
    assert api_client.post(f'{API}/wallets/me/charge-card/', {'amount': '100',
                                                              'card_id': '00000000-0000-0000-0000-000000000000'},
                           format='json').status_code == 404
    paystack.rsps.add('POST', 'https://api.paystack.co/transaction/charge_authorization',
                      json={'status': True, 'data': {'reference': 'r', 'status': 'pending'}})
    assert api_client.post(f'{API}/wallets/me/charge-card/', {'amount': '100'}, format='json').status_code == 202

    paystack.add('POST', 'transfer', {'status': 'otp', 'transfer_code': 'TRF_o'})
    withdrawal = api_client.post(f'{API}/wallets/me/withdraw/', {'amount': '1000'}, format='json').json()
    paystack.add('POST', 'transfer/resend_otp', {})
    resent = api_client.post(f'{API}/wallets/me/resend-otp/', {'transaction_id': withdrawal['transaction']['id']},
                             format='json')
    assert resent.status_code == 200
    assert api_client.post(f'{API}/wallets/me/resend-otp/', {}, format='json').status_code == 400
    assert api_client.post(f'{API}/wallets/me/finalize-withdrawal/', {'otp': '1'}, format='json').status_code == 400
    missing = api_client.post(f'{API}/wallets/me/finalize-withdrawal/',
                              {'otp': '1', 'reference': 'nope'}, format='json')
    assert missing.status_code == 404

    paystack.add('POST', 'transfer', {'status': 'failed', 'reason': 'Account closed'})
    failed = api_client.post(f'{API}/wallets/me/withdraw/', {'amount': '1000'}, format='json')
    assert failed.status_code == 400 and failed.json()['status'] == 'failed'


def test_dva_and_identity_endpoints(api_client, paystack, wallet):
    wallet.paystack_customer_code = 'CUS_ada'
    wallet.dedicated_account_number = '9930000001'
    wallet.dedicated_account_bank_slug = 'wema-bank'
    wallet.save()
    assert api_client.get(f'{API}/wallets/me/dedicated-account/').json()['account_number'] == '9930000001'
    paystack.add('GET', 'dedicated_account/requery', {})
    assert api_client.post(f'{API}/wallets/me/requery-dedicated-account/').status_code == 200
    paystack.add('POST', 'customer/CUS_ada/identification', {})
    validated = api_client.post(f'{API}/wallets/me/validate-customer/', {
        'first_name': 'Ada', 'last_name': 'Obi', 'bvn': '22222222222', 'bank_code': '058',
        'account_number': '0123456789'}, format='json')
    assert validated.status_code == 202
    with override_settings(WALLET_ENABLE_DEDICATED_ACCOUNTS=False):
        assert api_client.get(f'{API}/wallets/me/dedicated-account/').status_code == 403
        assert api_client.post(f'{API}/wallets/me/requery-dedicated-account/').status_code == 403
    with override_settings(WALLET_ENABLE_RECIPIENT_LOOKUP=False):
        assert api_client.get(f'{API}/wallets/lookup/', {'recipient': 'x'}).status_code == 403


def test_transaction_verify_and_staff_refund(api_client, staff_client, paystack, service, wallet):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = service.initialize_deposit(wallet, 2000)['reference']
    paystack.add('GET', f'transaction/verify/{reference}', charge_data(reference, 200000))
    verified = api_client.post(f'{API}/transactions/verify/', {'reference': reference}, format='json')
    assert verified.json()['status'] == 'success'
    assert api_client.post(f'{API}/transactions/verify/', {'reference': 'x'}, format='json').status_code == 404

    txn = Transaction.objects.get(reference=reference)
    assert api_client.post(f'{API}/transactions/{txn.pk}/refund/').status_code == 403
    paystack.add('POST', 'refund', {'id': 5, 'status': 'pending'})
    refunded = staff_client.post(f'{API}/transactions/{txn.pk}/refund/', {'amount': '500'}, format='json')
    assert refunded.status_code == 201 and refunded.json()['transaction_type'] == 'refund'

    not_deposit = api_client.post(f'{API}/transactions/verify/',
                                  {'reference': Transaction.objects.filter(transaction_type='refund').get().reference},
                                  format='json')
    assert not_deposit.status_code == 409


def test_settlement_finalize_retry_and_errors(api_client, paystack, funded_wallet, bank_account):
    assert api_client.post(f'{API}/settlements/', {'amount': '100',
                                                   'bank_account_id': '00000000-0000-0000-0000-000000000000'},
                           format='json').status_code == 404
    paystack.add('POST', 'transfer', {'status': 'otp', 'transfer_code': 'TRF_s'})
    settlement_id = api_client.post(f'{API}/settlements/', {'amount': '100'}, format='json').json()['id']
    paystack.add('POST', 'transfer/finalize_transfer', {'status': 'success'})
    finalized = api_client.post(f'{API}/settlements/{settlement_id}/finalize/', {'otp': '123'}, format='json')
    assert finalized.json()['status'] == 'success'
    retry = api_client.post(f'{API}/settlements/{settlement_id}/retry/')
    assert retry.status_code == 400 and retry.json()['code'] == 'settlement_error'
    assert Settlement.objects.get().status == 'success'


# ---------------------------------------------------------------------------
# Permissions module
# ---------------------------------------------------------------------------

def test_permission_classes(user, other_user, wallet, other_wallet, staff_user):
    request = SimpleNamespace(user=user)
    txn = fund(wallet, 10) and Transaction.objects.get(wallet=wallet)
    assert IsWalletOwner().has_object_permission(request, None, wallet)
    assert IsWalletOwner().has_object_permission(request, None, txn)
    assert not IsWalletOwner().has_object_permission(request, None, other_wallet)

    user.wallet = wallet
    assert HasOperationalWallet().has_permission(request, None)
    wallet.is_locked = True
    assert not HasOperationalWallet().has_permission(request, None)

    endpoint = WebhookEndpoint.objects.create(name='n', url='https://hooks.test/p')
    assert IsWebhookEndpointOwner().has_object_permission(SimpleNamespace(user=staff_user), None, endpoint)
    assert not IsWebhookEndpointOwner().has_object_permission(request, None, endpoint)
    endpoint.wallets.add(wallet)
    assert IsWebhookEndpointOwner().has_object_permission(request, None, endpoint)


def test_admin_actions_through_services(client, staff_user, paystack, service, funded_wallet, other_wallet,
                                        bank_account):
    client.force_login(staff_user)
    debit = service.transfer(funded_wallet, other_wallet, 100)
    client.post('/admin/wallet/transaction/', {'action': 'reverse', '_selected_action': [debit.pk]})
    debit.refresh_from_db()
    assert debit.status == 'reversed'

    client.post('/admin/wallet/wallet/', {'action': 'unlock_wallets', '_selected_action': [funded_wallet.pk]})
    client.post('/admin/wallet/wallet/', {'action': 'reset_pins', '_selected_action': [funded_wallet.pk]})
    paystack.error('POST', 'customer', 'Invalid email')
    response = client.post('/admin/wallet/wallet/', {'action': 'create_paystack_customers',
                                                     '_selected_action': [funded_wallet.pk]}, follow=True)
    assert b'Invalid email' in response.content

    paystack.add('GET', 'bank', [], meta={})
    client.post('/admin/wallet/bank/', {'action': 'sync_from_paystack',
                                        '_selected_action': [bank_account.bank.pk]})
    client.post('/admin/wallet/bankaccount/', {'action': 'create_recipient_codes',
                                               '_selected_action': [bank_account.pk]})
    assert client.get(f'/admin/wallet/transaction/{debit.pk}/change/').status_code == 200
