import json

import pytest
import requests
import responses as responses_lib
from django.test import override_settings

from wallet.exceptions import (
    InvalidPaystackResponse,
    InvalidWebhookSignature,
    PaystackAPIError,
    PaystackConfigurationError,
)
from wallet.paystack import PaystackClient, compute_signature, verify_signature
from wallet.services.paystack_service import PaystackService

BASE = 'https://api.paystack.co'

# (resource, method, args, kwargs, http_method, path)
ENDPOINTS = [
    ('transactions', 'initialize', (), {'email': 'a@b.co', 'amount': 5000}, 'POST', 'transaction/initialize'),
    ('transactions', 'verify', ('ref1',), {}, 'GET', 'transaction/verify/ref1'),
    ('transactions', 'list', (), {'perPage': 5}, 'GET', 'transaction'),
    ('transactions', 'fetch', (9,), {}, 'GET', 'transaction/9'),
    ('transactions', 'charge_authorization', (), {'email': 'a@b.co', 'amount': 1, 'authorization_code': 'A'},
     'POST', 'transaction/charge_authorization'),
    ('transactions', 'timeline', ('ref1',), {}, 'GET', 'transaction/timeline/ref1'),
    ('transactions', 'totals', (), {}, 'GET', 'transaction/totals'),
    ('transactions', 'export', (), {}, 'GET', 'transaction/export'),
    ('transactions', 'partial_debit', ('A', 'NGN', 100, 'a@b.co'), {}, 'POST', 'transaction/partial_debit'),
    ('splits', 'create', ('s', 'percentage', 'NGN', [], 'account'), {}, 'POST', 'split'),
    ('splits', 'list', (), {}, 'GET', 'split'),
    ('splits', 'fetch', (1,), {}, 'GET', 'split/1'),
    ('splits', 'update', (1,), {'name': 'x'}, 'PUT', 'split/1'),
    ('splits', 'add_subaccount', (1, 'ACCT', 10), {}, 'POST', 'split/1/subaccount/add'),
    ('splits', 'remove_subaccount', (1, 'ACCT'), {}, 'POST', 'split/1/subaccount/remove'),
    ('terminals', 'send_event', ('T1', 'invoice', 'process', {}), {}, 'POST', 'terminal/T1/event'),
    ('terminals', 'fetch_event_status', ('T1', 'E1'), {}, 'GET', 'terminal/T1/event/E1'),
    ('terminals', 'fetch_status', ('T1',), {}, 'GET', 'terminal/T1/presence'),
    ('terminals', 'list', (), {}, 'GET', 'terminal'),
    ('terminals', 'fetch', ('T1',), {}, 'GET', 'terminal/T1'),
    ('terminals', 'update', ('T1',), {'name': 'x'}, 'PUT', 'terminal/T1'),
    ('terminals', 'commission', ('SN',), {}, 'POST', 'terminal/commission_device'),
    ('terminals', 'decommission', ('SN',), {}, 'POST', 'terminal/decommission_device'),
    ('virtual_terminals', 'create', ('vt', []), {}, 'POST', 'virtual_terminal'),
    ('virtual_terminals', 'list', (), {}, 'GET', 'virtual_terminal'),
    ('virtual_terminals', 'fetch', ('VT',), {}, 'GET', 'virtual_terminal/VT'),
    ('virtual_terminals', 'update', ('VT', 'n'), {}, 'PUT', 'virtual_terminal/VT'),
    ('virtual_terminals', 'deactivate', ('VT',), {}, 'PUT', 'virtual_terminal/VT/deactivate'),
    ('virtual_terminals', 'assign_destination', ('VT', []), {}, 'POST', 'virtual_terminal/VT/destination/assign'),
    ('virtual_terminals', 'unassign_destination', ('VT', []), {}, 'POST',
     'virtual_terminal/VT/destination/unassign'),
    ('virtual_terminals', 'add_split_code', ('VT', 'SPL'), {}, 'PUT', 'virtual_terminal/VT/split_code'),
    ('virtual_terminals', 'remove_split_code', ('VT', 'SPL'), {}, 'DELETE', 'virtual_terminal/VT/split_code'),
    ('customers', 'create', ('a@b.co',), {}, 'POST', 'customer'),
    ('customers', 'list', (), {}, 'GET', 'customer'),
    ('customers', 'fetch', ('CUS_1',), {}, 'GET', 'customer/CUS_1'),
    ('customers', 'update', ('CUS_1',), {'first_name': 'A'}, 'PUT', 'customer/CUS_1'),
    ('customers', 'validate', ('CUS_1', 'A', 'B', 'bank_account'), {}, 'POST', 'customer/CUS_1/identification'),
    ('customers', 'set_risk_action', ('CUS_1', 'deny'), {}, 'POST', 'customer/set_risk_action'),
    ('customers', 'deactivate_authorization', ('AUTH',), {}, 'POST', 'customer/deactivate_authorization'),
    ('direct_debit', 'initialize_authorization', ('a@b.co',), {}, 'POST', 'customer/authorization/initialize'),
    ('direct_debit', 'verify_authorization', ('R',), {}, 'GET', 'customer/authorization/verify/R'),
    ('direct_debit', 'initialize', (1, {}, {}), {}, 'POST', 'customer/1/initialize-direct-debit'),
    ('direct_debit', 'activation_charge', (1, 2), {}, 'PUT', 'customer/1/directdebit-activation-charge'),
    ('direct_debit', 'mandate_authorizations', (1,), {}, 'GET', 'customer/1/directdebit-mandate-authorizations'),
    ('direct_debit', 'trigger_activation_charge', ([1],), {}, 'PUT', 'directdebit/activation-charge'),
    ('direct_debit', 'list_mandates', (), {}, 'GET', 'directdebit/mandate-authorizations'),
    ('dedicated_accounts', 'create', ('CUS_1',), {}, 'POST', 'dedicated_account'),
    ('dedicated_accounts', 'assign', ('a@b.co', 'A', 'B', '080', 'wema-bank'), {}, 'POST',
     'dedicated_account/assign'),
    ('dedicated_accounts', 'list', (), {}, 'GET', 'dedicated_account'),
    ('dedicated_accounts', 'fetch', (5,), {}, 'GET', 'dedicated_account/5'),
    ('dedicated_accounts', 'requery', ('012', 'wema-bank'), {}, 'GET', 'dedicated_account/requery'),
    ('dedicated_accounts', 'deactivate', (5,), {}, 'DELETE', 'dedicated_account/5'),
    ('dedicated_accounts', 'split', ('CUS_1',), {}, 'POST', 'dedicated_account/split'),
    ('dedicated_accounts', 'remove_split', ('012',), {}, 'DELETE', 'dedicated_account/split'),
    ('dedicated_accounts', 'providers', (), {}, 'GET', 'dedicated_account/available_providers'),
    ('apple_pay', 'register_domain', ('x.com',), {}, 'POST', 'apple-pay/domain'),
    ('apple_pay', 'list_domains', (), {}, 'GET', 'apple-pay/domain'),
    ('apple_pay', 'unregister_domain', ('x.com',), {}, 'DELETE', 'apple-pay/domain'),
    ('subaccounts', 'create', ('Biz', '058', '0123', 10), {}, 'POST', 'subaccount'),
    ('subaccounts', 'list', (), {}, 'GET', 'subaccount'),
    ('subaccounts', 'fetch', ('ACCT',), {}, 'GET', 'subaccount/ACCT'),
    ('subaccounts', 'update', ('ACCT',), {'active': True}, 'PUT', 'subaccount/ACCT'),
    ('plans', 'create', ('Gold', 5000, 'monthly'), {}, 'POST', 'plan'),
    ('plans', 'list', (), {}, 'GET', 'plan'),
    ('plans', 'fetch', ('PLN',), {}, 'GET', 'plan/PLN'),
    ('plans', 'update', ('PLN',), {'name': 'x'}, 'PUT', 'plan/PLN'),
    ('subscriptions', 'create', ('CUS', 'PLN'), {}, 'POST', 'subscription'),
    ('subscriptions', 'list', (), {}, 'GET', 'subscription'),
    ('subscriptions', 'fetch', ('SUB',), {}, 'GET', 'subscription/SUB'),
    ('subscriptions', 'enable', ('SUB', 'tok'), {}, 'POST', 'subscription/enable'),
    ('subscriptions', 'disable', ('SUB', 'tok'), {}, 'POST', 'subscription/disable'),
    ('subscriptions', 'generate_update_link', ('SUB',), {}, 'GET', 'subscription/SUB/manage/link'),
    ('subscriptions', 'send_update_link', ('SUB',), {}, 'POST', 'subscription/SUB/manage/email'),
    ('products', 'create', ('P', 'd', 100, 'NGN'), {}, 'POST', 'product'),
    ('products', 'list', (), {}, 'GET', 'product'),
    ('products', 'fetch', (1,), {}, 'GET', 'product/1'),
    ('products', 'update', (1,), {'name': 'x'}, 'PUT', 'product/1'),
    ('payment_pages', 'create', ('Page',), {}, 'POST', 'page'),
    ('payment_pages', 'list', (), {}, 'GET', 'page'),
    ('payment_pages', 'fetch', ('slug',), {}, 'GET', 'page/slug'),
    ('payment_pages', 'update', ('slug',), {'name': 'x'}, 'PUT', 'page/slug'),
    ('payment_pages', 'check_slug', ('slug',), {}, 'GET', 'page/check_slug_availability/slug'),
    ('payment_pages', 'add_products', (1, [2]), {}, 'POST', 'page/1/product'),
    ('payment_requests', 'create', ('CUS',), {}, 'POST', 'paymentrequest'),
    ('payment_requests', 'list', (), {}, 'GET', 'paymentrequest'),
    ('payment_requests', 'fetch', ('PRQ',), {}, 'GET', 'paymentrequest/PRQ'),
    ('payment_requests', 'verify', ('PRQ',), {}, 'GET', 'paymentrequest/verify/PRQ'),
    ('payment_requests', 'notify', ('PRQ',), {}, 'POST', 'paymentrequest/notify/PRQ'),
    ('payment_requests', 'totals', (), {}, 'GET', 'paymentrequest/totals'),
    ('payment_requests', 'finalize', ('PRQ',), {}, 'POST', 'paymentrequest/finalize/PRQ'),
    ('payment_requests', 'update', ('PRQ',), {'amount': 1}, 'PUT', 'paymentrequest/PRQ'),
    ('payment_requests', 'archive', ('PRQ',), {}, 'POST', 'paymentrequest/archive/PRQ'),
    ('settlements', 'list', (), {}, 'GET', 'settlement'),
    ('settlements', 'transactions', (7,), {}, 'GET', 'settlement/7/transactions'),
    ('transfer_recipients', 'create', ('nuban', 'Ada'), {}, 'POST', 'transferrecipient'),
    ('transfer_recipients', 'bulk_create', ([],), {}, 'POST', 'transferrecipient/bulk'),
    ('transfer_recipients', 'list', (), {}, 'GET', 'transferrecipient'),
    ('transfer_recipients', 'fetch', ('RCP',), {}, 'GET', 'transferrecipient/RCP'),
    ('transfer_recipients', 'update', ('RCP',), {'name': 'x'}, 'PUT', 'transferrecipient/RCP'),
    ('transfer_recipients', 'delete', ('RCP',), {}, 'DELETE', 'transferrecipient/RCP'),
    ('transfers', 'initiate', (100, 'RCP'), {}, 'POST', 'transfer'),
    ('transfers', 'finalize', ('TRF', '123'), {}, 'POST', 'transfer/finalize_transfer'),
    ('transfers', 'bulk_initiate', ([],), {}, 'POST', 'transfer/bulk'),
    ('transfers', 'list', (), {}, 'GET', 'transfer'),
    ('transfers', 'fetch', ('TRF',), {}, 'GET', 'transfer/TRF'),
    ('transfers', 'verify', ('ref',), {}, 'GET', 'transfer/verify/ref'),
    ('transfer_control', 'balance', (), {}, 'GET', 'balance'),
    ('transfer_control', 'ledger', (), {}, 'GET', 'balance/ledger'),
    ('transfer_control', 'resend_otp', ('TRF',), {}, 'POST', 'transfer/resend_otp'),
    ('transfer_control', 'disable_otp', (), {}, 'POST', 'transfer/disable_otp'),
    ('transfer_control', 'finalize_disable_otp', ('123',), {}, 'POST', 'transfer/disable_otp_finalize'),
    ('transfer_control', 'enable_otp', (), {}, 'POST', 'transfer/enable_otp'),
    ('bulk_charges', 'initiate', ([],), {}, 'POST', 'bulkcharge'),
    ('bulk_charges', 'list', (), {}, 'GET', 'bulkcharge'),
    ('bulk_charges', 'fetch', ('BCH',), {}, 'GET', 'bulkcharge/BCH'),
    ('bulk_charges', 'charges', ('BCH',), {}, 'GET', 'bulkcharge/BCH/charges'),
    ('bulk_charges', 'pause', ('BCH',), {}, 'GET', 'bulkcharge/pause/BCH'),
    ('bulk_charges', 'resume', ('BCH',), {}, 'GET', 'bulkcharge/resume/BCH'),
    ('integration', 'fetch_timeout', (), {}, 'GET', 'integration/payment_session_timeout'),
    ('integration', 'update_timeout', (30,), {}, 'PUT', 'integration/payment_session_timeout'),
    ('charges', 'create', ('a@b.co', 100), {}, 'POST', 'charge'),
    ('charges', 'submit_pin', ('1234', 'R'), {}, 'POST', 'charge/submit_pin'),
    ('charges', 'submit_otp', ('123', 'R'), {}, 'POST', 'charge/submit_otp'),
    ('charges', 'submit_phone', ('080', 'R'), {}, 'POST', 'charge/submit_phone'),
    ('charges', 'submit_birthday', ('1990-01-01', 'R'), {}, 'POST', 'charge/submit_birthday'),
    ('charges', 'submit_address', ('a', 'b', 'c', 'd', 'R'), {}, 'POST', 'charge/submit_address'),
    ('charges', 'check_pending', ('R',), {}, 'GET', 'charge/R'),
    ('disputes', 'list', (), {}, 'GET', 'dispute'),
    ('disputes', 'fetch', (1,), {}, 'GET', 'dispute/1'),
    ('disputes', 'list_for_transaction', (1,), {}, 'GET', 'dispute/transaction/1'),
    ('disputes', 'update', (1, 100), {}, 'PUT', 'dispute/1'),
    ('disputes', 'add_evidence', (1, 'a@b.co', 'A', '080', 'svc'), {}, 'POST', 'dispute/1/evidence'),
    ('disputes', 'upload_url', (1, 'f.pdf'), {}, 'GET', 'dispute/1/upload_url'),
    ('disputes', 'resolve', (1, 'declined', 'm', 100, 'f.pdf'), {}, 'PUT', 'dispute/1/resolve'),
    ('disputes', 'export', (), {}, 'GET', 'dispute/export'),
    ('refunds', 'create', ('ref',), {}, 'POST', 'refund'),
    ('refunds', 'list', (), {}, 'GET', 'refund'),
    ('refunds', 'fetch', (1,), {}, 'GET', 'refund/1'),
    ('verification', 'resolve_account', ('0123', '058'), {}, 'GET', 'bank/resolve'),
    ('verification', 'validate_account', ('A', '0123', 'personal', '632005', 'ZA', 'identityNumber'), {}, 'POST',
     'bank/validate'),
    ('verification', 'resolve_card_bin', ('408408',), {}, 'GET', 'decision/bin/408408'),
    ('misc', 'list_banks', (), {'country': 'nigeria'}, 'GET', 'bank'),
    ('misc', 'list_countries', (), {}, 'GET', 'country'),
    ('misc', 'list_states', ('US',), {}, 'GET', 'address_verification/states'),
]


@pytest.fixture
def rsps():
    with responses_lib.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.mark.parametrize('resource,method,args,kwargs,http_method,path', ENDPOINTS,
                         ids=[f"{e[0]}.{e[1]}" for e in ENDPOINTS])
def test_every_endpoint(rsps, resource, method, args, kwargs, http_method, path):
    rsps.add(http_method, f'{BASE}/{path}', json={'status': True, 'message': 'ok', 'data': {'ok': 1}})
    client = PaystackClient()
    result = getattr(getattr(client, resource), method)(*args, **kwargs)
    assert result == {'ok': 1}
    request = rsps.calls[0].request
    from django.conf import settings
    assert request.headers['Authorization'] == f'Bearer {settings.PAYSTACK_SECRET_KEY}'
    if request.body:
        assert None not in json.loads(request.body).values() if isinstance(json.loads(request.body), dict) else True


def test_none_values_are_not_sent(rsps):
    rsps.add('POST', f'{BASE}/transaction/initialize', json={'status': True, 'data': {}})
    PaystackClient().transactions.initialize(email='a@b.co', amount=100, reference=None, metadata={'k': 'v'})
    assert json.loads(rsps.calls[0].request.body) == {'email': 'a@b.co', 'amount': 100, 'metadata': {'k': 'v'}}


def test_query_params_for_get(rsps):
    rsps.add('GET', f'{BASE}/bank/resolve', json={'status': True, 'data': {'account_name': 'ADA'}})
    PaystackClient().verification.resolve_account('0123456789', '058')
    assert 'account_number=0123456789' in rsps.calls[0].request.url
    assert 'bank_code=058' in rsps.calls[0].request.url


def test_rejection_is_definitive(rsps):
    rsps.add('POST', f'{BASE}/transfer', json={'status': False, 'message': 'Insufficient balance'}, status=400)
    with pytest.raises(PaystackAPIError) as excinfo:
        PaystackClient().transfers.initiate(amount=100, recipient='RCP')
    assert excinfo.value.is_definitive
    assert excinfo.value.status_code == 400
    assert excinfo.value.paystack_message == 'Insufficient balance'


def test_status_false_with_200_is_an_error(rsps):
    rsps.add('GET', f'{BASE}/balance', json={'status': False, 'message': 'nope'}, status=200)
    with pytest.raises(PaystackAPIError):
        PaystackClient().transfer_control.balance()


def test_get_is_retried_on_5xx(rsps):
    rsps.add('GET', f'{BASE}/balance', json={}, status=502)
    rsps.add('GET', f'{BASE}/balance', json={'status': True, 'data': [{'balance': 10}]})
    client = PaystackClient(max_retries=2)
    client_sleep = pytest.MonkeyPatch()
    client_sleep.setattr('wallet.paystack.client.time.sleep', lambda *_: None)
    try:
        assert client.transfer_control.balance() == [{'balance': 10}]
    finally:
        client_sleep.undo()
    assert len(rsps.calls) == 2


def test_post_is_never_retried(rsps):
    rsps.add('POST', f'{BASE}/transfer', json={}, status=503, body=None)
    with pytest.raises(PaystackAPIError) as excinfo:
        PaystackClient(max_retries=3).transfers.initiate(amount=1, recipient='R')
    assert len(rsps.calls) == 1
    assert not excinfo.value.is_definitive


def test_network_error_is_not_definitive(rsps, monkeypatch):
    monkeypatch.setattr('wallet.paystack.client.time.sleep', lambda *_: None)
    rsps.add('GET', f'{BASE}/balance', body=requests.ConnectionError('down'))
    rsps.add('GET', f'{BASE}/balance', body=requests.ConnectionError('down'))
    with pytest.raises(PaystackAPIError) as excinfo:
        PaystackClient(max_retries=1).transfer_control.balance()
    assert excinfo.value.status_code is None
    assert not excinfo.value.is_definitive


def test_non_json_response(rsps):
    rsps.add('GET', f'{BASE}/balance', body='<html>gateway</html>', status=502)
    with pytest.raises(InvalidPaystackResponse) as excinfo:
        PaystackClient().transfer_control.balance()
    assert not excinfo.value.is_definitive


def test_missing_secret_key():
    with override_settings(PAYSTACK_SECRET_KEY=''):
        with pytest.raises(PaystackConfigurationError):
            PaystackClient().transfer_control.balance()


def test_paginate_walks_pages(rsps):
    rsps.add('GET', f'{BASE}/customer', json={'status': True, 'data': [1, 2], 'meta': {'pageCount': 2}})
    rsps.add('GET', f'{BASE}/customer', json={'status': True, 'data': [3], 'meta': {'pageCount': 2}})
    assert list(PaystackClient().paginate('customer', per_page=2)) == [1, 2, 3]


def test_raw_response(rsps):
    rsps.add('GET', f'{BASE}/balance', json={'status': True, 'message': 'hi', 'data': [], 'meta': {'total': 0}})
    body = PaystackClient().request('GET', 'balance', raw=True)
    assert body['meta'] == {'total': 0}


def test_settings_are_resolved_lazily(rsps):
    rsps.add('GET', 'https://sandbox.example/balance', json={'status': True, 'data': []})
    client = PaystackClient()
    with override_settings(PAYSTACK_API_URL='https://sandbox.example/'):
        client.transfer_control.balance()
    assert client.is_test_mode


def test_signatures():
    body = b'{"event":"charge.success"}'
    signature = compute_signature(body)
    assert verify_signature(body, signature)
    assert not verify_signature(body, 'bad')
    assert not verify_signature(body, '')
    client = PaystackService()
    assert client.verify_webhook_signature(signature, body)
    with pytest.raises(InvalidWebhookSignature):
        client.verify_webhook_signature('bad', body)


def test_legacy_aliases(rsps):
    rsps.add('POST', f'{BASE}/transaction/initialize', json={'status': True, 'data': {'a': 1}})
    rsps.add('GET', f'{BASE}/transaction/verify/r', json={'status': True, 'data': {'b': 1}})
    rsps.add('POST', f'{BASE}/transfer', json={'status': True, 'data': {'c': 1}})
    client = PaystackService()
    assert client.initialize_transaction(100, 'a@b.co') == {'a': 1}
    assert client.verify_transaction('r') == {'b': 1}
    assert client.initiate_transfer(100, 'RCP') == {'c': 1}
