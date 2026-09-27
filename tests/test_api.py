import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from tests.conftest import charge_data, fund, money
from wallet.models import BankAccount, Card, Settlement, SettlementSchedule, Transaction

pytestmark = pytest.mark.django_db

API = '/wallet/api'


# ---------------------------------------------------------------------------
# Auth & ownership
# ---------------------------------------------------------------------------

def test_authentication_required():
    client = APIClient()
    assert client.get(f'{API}/wallets/').status_code == 403
    assert client.get(f'{API}/transactions/').status_code == 403


def test_wallet_me_and_list(api_client, wallet):
    response = api_client.get(f'{API}/wallets/me/')
    assert response.status_code == 200
    assert response.json()['id'] == str(wallet.pk)
    assert response.json()['balance'] == '0.00'
    assert api_client.get(f'{API}/wallets/{wallet.pk}/').status_code == 200
    assert len(api_client.get(f'{API}/wallets/').json()['results']) == 1


def test_wallet_created_on_first_access(api_client, user):
    response = api_client.get(f'{API}/wallets/me/balance/')
    assert response.status_code == 200
    assert response.json() == {**response.json(), 'balance': '0.00', 'currency': 'NGN'}


def test_cannot_see_other_wallets_or_transactions(api_client, wallet, other_wallet, service):
    fund(other_wallet, 500)
    assert api_client.get(f'{API}/wallets/{other_wallet.pk}/').status_code == 404
    other_txn = Transaction.objects.get(wallet=other_wallet)
    assert api_client.get(f'{API}/transactions/{other_txn.pk}/').status_code == 404
    assert api_client.get(f'{API}/transactions/').json()['count'] == 0


def test_update_tag_and_phone(api_client, wallet):
    response = api_client.patch(f'{API}/wallets/me/', {'tag': 'ada_pay', 'phone_number': '0803 123 4567'},
                                format='json')
    assert response.status_code == 200
    assert response.json()['tag'] == 'ada_pay'
    assert response.json()['phone_number'] == '+2348031234567'
    bad = api_client.patch(f'{API}/wallets/me/', {'phone_number': 'abc'}, format='json')
    assert bad.status_code == 400 and bad.json()['code'] == 'invalid_phone_number'


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------

def test_deposit_endpoint(api_client, paystack, wallet):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'https://checkout', 'access_code': 'ac'})
    response = api_client.post(f'{API}/wallets/me/deposit/', {'amount': '2500.00', 'channels': ['card', 'ussd']},
                               format='json')
    assert response.status_code == 201
    assert response.json()['authorization_url'] == 'https://checkout'
    assert paystack.last_body('transaction/initialize')['channels'] == ['card', 'ussd']
    txn = Transaction.objects.get(reference=response.json()['reference'])
    assert txn.ip_address == '127.0.0.1'

    paystack.add('GET', f'transaction/verify/{txn.reference}', charge_data(txn.reference, 250000))
    verified = api_client.post(f'{API}/wallets/me/verify-deposit/', {'reference': txn.reference}, format='json')
    assert verified.status_code == 200 and verified.json()['status'] == 'success'
    assert api_client.get(f'{API}/wallets/me/balance/').json()['balance'] == '2500.00'


def test_deposit_validation_and_gateway_errors(api_client, paystack, wallet):
    assert api_client.post(f'{API}/wallets/me/deposit/', {'amount': '-5'}, format='json').status_code == 400
    assert api_client.post(f'{API}/wallets/me/deposit/', {'amount': '100', 'channels': ['crypto']},
                           format='json').status_code == 400
    paystack.add('POST', 'transaction/initialize', status=500, body={'status': False, 'message': 'down'})
    response = api_client.post(f'{API}/wallets/me/deposit/', {'amount': '100'}, format='json')
    assert response.status_code == 502
    assert response.json()['code'] == 'paystack_error'


def test_fee_bearer_override_is_restricted(api_client, staff_client, paystack, wallet):
    body = {'amount': '1000', 'fee_bearer': 'platform'}
    response = api_client.post(f'{API}/wallets/me/deposit/', body, format='json')
    assert response.status_code == 400 and 'fee_bearer' in response.json()
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    with override_settings(WALLET_ALLOW_FEE_BEARER_OVERRIDE=True):
        assert api_client.post(f'{API}/wallets/me/deposit/', body, format='json').status_code == 201


def test_feature_switch_returns_403(api_client, wallet):
    with override_settings(WALLET_ENABLE_DEPOSITS=False):
        response = api_client.post(f'{API}/wallets/me/deposit/', {'amount': '1000'}, format='json')
    assert response.status_code == 403 and response.json()['code'] == 'feature_disabled'
    with override_settings(WALLET_ENABLE_CARDS=False):
        assert api_client.get(f'{API}/cards/').status_code == 403


# ---------------------------------------------------------------------------
# Transfers, lookup & PIN
# ---------------------------------------------------------------------------

def test_transfer_by_phone(api_client, funded_wallet, other_wallet, service):
    service.set_phone_number(other_wallet, '08099998888')
    lookup = api_client.get(f'{API}/wallets/lookup/', {'recipient': '0809 999 8888'})
    assert lookup.status_code == 200 and lookup.json()['name'] == 'Bola A.'

    response = api_client.post(f'{API}/wallets/me/transfer/', {'phone_number': '08099998888', 'amount': '1200'},
                               format='json')
    assert response.status_code == 201
    assert response.json()['direction'] == 'debit' and response.json()['total_amount'] == '1200.00'
    other_wallet.refresh_from_db()
    assert other_wallet.balance == money(1200)


def test_transfer_errors(api_client, funded_wallet):
    missing = api_client.post(f'{API}/wallets/me/transfer/', {'recipient': 'ghost', 'amount': '10'}, format='json')
    assert missing.status_code == 404 and missing.json()['code'] == 'recipient_not_found'
    assert api_client.post(f'{API}/wallets/me/transfer/', {'amount': '10'}, format='json').status_code == 400
    poor = api_client.post(f'{API}/wallets/me/transfer/', {'recipient': 'ada', 'amount': '10'}, format='json')
    assert poor.status_code == 400 and poor.json()['code'] == 'recipient_error'


@override_settings(WALLET_REQUIRE_TRANSACTION_PIN=True, WALLET_PIN_MAX_ATTEMPTS=2)
def test_pin_enforcement(api_client, funded_wallet, other_wallet):
    body = {'recipient': 'bola', 'amount': '100'}
    assert api_client.post(f'{API}/wallets/me/transfer/', body, format='json').json()['code'] == 'pin_required'

    weak = api_client.post(f'{API}/wallets/me/set-pin/', {'pin': '1234', 'confirm_pin': '1234'}, format='json')
    assert weak.status_code == 400
    ok = api_client.post(f'{API}/wallets/me/set-pin/', {'pin': '4826', 'confirm_pin': '4826'}, format='json')
    assert ok.status_code == 200
    change = api_client.post(f'{API}/wallets/me/set-pin/', {'pin': '5937', 'confirm_pin': '5937'}, format='json')
    assert change.json()['code'] == 'pin_required'

    assert api_client.post(f'{API}/wallets/me/transfer/', {**body, 'pin': '4826'}, format='json').status_code == 201
    assert api_client.post(f'{API}/wallets/me/transfer/', {**body, 'pin': '0000'},
                           format='json').json()['code'] == 'invalid_pin'
    locked = api_client.post(f'{API}/wallets/me/transfer/', {**body, 'pin': '0000'}, format='json')
    assert locked.status_code == 403 and locked.json()['code'] == 'pin_locked'


def test_pay_and_escrow_release(api_client, funded_wallet, other_wallet):
    response = api_client.post(f'{API}/wallets/me/pay/', {'amount': '3000', 'merchant': 'bola', 'escrow': True},
                               format='json')
    assert response.status_code == 201 and response.json()['status'] == 'pending'
    released = api_client.post(f"{API}/transactions/{response.json()['id']}/release/")
    assert released.status_code == 200 and released.json()['status'] == 'success'
    other_wallet.refresh_from_db()
    assert other_wallet.balance == money(3000)


def test_fee_quote(api_client, wallet):
    with override_settings(WALLET_ENABLE_FEES=True):
        response = api_client.post(f'{API}/wallets/fee-quote/', {'amount': '10000', 'transaction_type': 'withdrawal'},
                                   format='json')
    assert response.status_code == 200
    assert response.json()['fee_amount'] == '25.00'
    assert response.json()['customer_pays'] == '10025.00'


# ---------------------------------------------------------------------------
# Withdrawals & bank accounts
# ---------------------------------------------------------------------------

def test_withdraw_otp_flow(api_client, paystack, funded_wallet, bank_account):
    paystack.add('POST', 'transfer', {'reference': 'wdr-api-reference-0001', 'status': 'otp',
                                      'transfer_code': 'TRF_api'})
    response = api_client.post(f'{API}/wallets/me/withdraw/', {'amount': '5000',
                                                               'reference': 'wdr-api-reference-0001'}, format='json')
    assert response.status_code == 202 and response.json()['status'] == 'pending_otp'

    paystack.add('POST', 'transfer/finalize_transfer', {'reference': 'wdr-api-reference-0001', 'status': 'success'})
    final = api_client.post(f'{API}/wallets/me/finalize-withdrawal/',
                            {'otp': '123456', 'transfer_code': 'TRF_api'}, format='json')
    assert final.status_code == 200 and final.json()['status'] == 'success'


def test_withdraw_errors(api_client, paystack, funded_wallet, bank_account):
    none = api_client.post(f'{API}/wallets/me/withdraw/', {'amount': '5000',
                                                           'bank_account_id': '00000000-0000-0000-0000-000000000000'},
                           format='json')
    assert none.status_code == 404
    poor = api_client.post(f'{API}/wallets/me/withdraw/', {'amount': '5000000'}, format='json')
    assert poor.status_code == 400 and poor.json()['code'] == 'insufficient_funds'
    paystack.error('POST', 'transfer', 'Insufficient Paystack balance')
    rejected = api_client.post(f'{API}/wallets/me/withdraw/', {'amount': '5000'}, format='json')
    assert rejected.status_code == 502 and rejected.json()['detail'] == 'Insufficient Paystack balance'
    assert api_client.get(f'{API}/wallets/me/balance/').json()['balance'] == '100000.00'


def test_bank_account_endpoints(api_client, paystack, wallet, bank):
    assert api_client.get(f'{API}/banks/', {'search': 'test'}).json()['count'] == 1
    paystack.add('GET', 'bank/resolve', {'account_number': '0123456789', 'account_name': 'ADA OBI'})
    resolved = api_client.post(f'{API}/bank-accounts/resolve/', {'bank_code': '058', 'account_number': '0123456789'},
                               format='json')
    assert resolved.json()['account_name'] == 'ADA OBI'

    paystack.add('GET', 'bank/resolve', {'account_number': '0123456789', 'account_name': 'ADA OBI'})
    paystack.add('POST', 'transferrecipient', {'recipient_code': 'RCP_api', 'id': 3})
    created = api_client.post(f'{API}/bank-accounts/', {'bank_code': '058', 'account_number': '0123456789'},
                              format='json')
    assert created.status_code == 201 and created.json()['can_receive_transfers']
    account_id = created.json()['id']
    assert api_client.post(f'{API}/bank-accounts/{account_id}/set-default/').status_code == 200
    assert api_client.delete(f'{API}/bank-accounts/{account_id}/').status_code == 204
    assert not BankAccount.objects.get(pk=account_id).is_active
    assert api_client.post(f'{API}/bank-accounts/', {'bank_code': '058', 'account_number': 'abc'},
                           format='json').status_code == 400


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def test_card_endpoints(api_client, paystack, card):
    assert api_client.get(f'{API}/cards/').json()['results'][0]['last_four'] == '4081'
    paystack.rsps.add('POST', 'https://api.paystack.co/transaction/charge_authorization',
                      json={'status': True, 'data': {'reference': 'r', 'status': 'send_otp'}})
    charge = api_client.post(f'{API}/cards/{card.pk}/charge/', {'amount': '1000'}, format='json')
    assert charge.status_code == 202
    assert api_client.post(f'{API}/cards/{card.pk}/set-default/').status_code == 200
    paystack.add('POST', 'customer/deactivate_authorization', {})
    assert api_client.delete(f'{API}/cards/{card.pk}/').status_code == 204
    assert not Card.objects.get(pk=card.pk).is_active


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def test_transaction_list_filters_and_statement(api_client, service, funded_wallet, other_wallet):
    service.transfer(funded_wallet, other_wallet, 100)
    assert api_client.get(f'{API}/transactions/', {'type': 'transfer'}).json()['count'] == 1
    assert api_client.get(f'{API}/transactions/', {'direction': 'credit'}).json()['count'] == 1
    assert api_client.get(f'{API}/wallets/me/transactions/', {'status': 'success'}).json()['count'] == 2
    statement = api_client.get(f'{API}/wallets/me/statement/').json()['results']
    assert [row['balance_after'] for row in statement] == ['100000.00', '99900.00']
    stats = api_client.get(f'{API}/transactions/statistics/').json()
    assert stats['total_count'] == 2
    assert api_client.get(f'{API}/transactions/summary/').status_code == 200


def test_transaction_export(api_client, funded_wallet):
    response = api_client.get(f'{API}/transactions/export/', {'export_format': 'csv'})
    assert response.status_code == 200 and response['Content-Type'] == 'text/csv'
    assert b'Reference' in response.content
    import importlib.util
    for export_format, library in (('xlsx', 'xlsxwriter'), ('pdf', 'reportlab')):
        response = api_client.get(f'{API}/transactions/export/', {'export_format': export_format})
        if importlib.util.find_spec(library):
            assert response.status_code == 200
        else:   # optional extra not installed: a clear message, not a crash
            assert response.status_code == 501 and 'django-paystack-wallet[export]' in response.json()['detail']
    assert api_client.get(f'{API}/transactions/export/', {'export_format': 'doc'}).status_code == 400


def test_staff_only_actions(api_client, staff_client, service, funded_wallet, other_wallet):
    debit = service.transfer(funded_wallet, other_wallet, 500)
    assert api_client.post(f'{API}/transactions/{debit.pk}/reverse/').status_code == 403
    response = staff_client.post(f'{API}/transactions/{debit.pk}/reverse/', {'reason': 'mistake'}, format='json')
    assert response.status_code == 201
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)


def test_cancel_pending_deposit(api_client, paystack, wallet):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = api_client.post(f'{API}/wallets/me/deposit/', {'amount': '100'}, format='json').json()['reference']
    txn = Transaction.objects.get(reference=reference)
    assert api_client.post(f'{API}/transactions/{txn.pk}/cancel/').json()['status'] == 'cancelled'
    again = api_client.post(f'{API}/transactions/{txn.pk}/cancel/')
    assert again.status_code == 409


# ---------------------------------------------------------------------------
# Settlements & schedules
# ---------------------------------------------------------------------------

def test_settlement_endpoints(api_client, paystack, funded_wallet, bank_account):
    paystack.rsps.add_callback('POST', 'https://api.paystack.co/transfer', callback=lambda request: (
        200, {}, '{"status": true, "data": {"status": "pending", "transfer_code": "TRF_s"}}'))
    response = api_client.post(f'{API}/settlements/', {'amount': '1000'}, format='json')
    assert response.status_code == 201 and response.json()['status'] == 'processing'
    assert api_client.get(f'{API}/settlements/').json()['count'] == 1
    assert api_client.get(f'{API}/settlements/statistics/').json()['total_count'] == 1
    settlement = Settlement.objects.get()
    paystack.add('GET', f'transfer/verify/{settlement.transaction.reference}', {'status': 'success'})
    verified = api_client.post(f'{API}/settlements/{settlement.pk}/verify/')
    assert verified.json()['status'] == 'success'


def test_schedule_crud(api_client, wallet, bank_account):
    created = api_client.post(f'{API}/settlement-schedules/', {
        'bank_account_id': str(bank_account.pk), 'schedule_type': 'weekly', 'day_of_week': 4,
    }, format='json')
    assert created.status_code == 201, created.json()
    assert created.json()['next_settlement']
    invalid = api_client.post(f'{API}/settlement-schedules/', {
        'bank_account_id': str(bank_account.pk), 'schedule_type': 'threshold',
    }, format='json')
    assert invalid.status_code == 400
    schedule_id = created.json()['id']
    assert api_client.post(f'{API}/settlement-schedules/{schedule_id}/deactivate/').json()['is_active'] is False
    updated = api_client.patch(f'{API}/settlement-schedules/{schedule_id}/', {'amount_threshold': '5000',
                                                                              'schedule_type': 'threshold'},
                               format='json')
    assert updated.status_code == 200 and updated.json()['amount_threshold'] == '5000.00'
    assert api_client.delete(f'{API}/settlement-schedules/{schedule_id}/').status_code == 204
    assert not SettlementSchedule.objects.exists()


# ---------------------------------------------------------------------------
# DVA, webhook admin, callback page, admin site
# ---------------------------------------------------------------------------

def test_dedicated_account_endpoint(api_client, paystack, wallet):
    assert api_client.get(f'{API}/wallets/me/dedicated-account/').status_code == 404
    paystack.add('POST', 'customer', {'customer_code': 'CUS_ada', 'id': 1})
    paystack.add('POST', 'dedicated_account', {'id': 2, 'account_number': '9930000002', 'account_name': 'ADA',
                                               'bank': {'name': 'Wema', 'slug': 'wema-bank'}})
    created = api_client.post(f'{API}/wallets/me/dedicated-account/', {}, format='json')
    assert created.status_code == 201 and created.json()['account_number'] == '9930000002'
    assert api_client.get(f'{API}/wallets/me/').json()['dedicated_account']['bank_name'] == 'Wema'


def test_webhook_admin_is_staff_only(api_client, staff_client):
    assert api_client.get(f'{API}/webhook-events/').status_code == 403
    assert staff_client.get(f'{API}/webhook-events/').status_code == 200
    assert staff_client.post(f'{API}/webhook-endpoints/', {'name': 'n', 'url': 'https://x.test/h'},
                             format='json').status_code == 201


def test_payment_callback_page(client, paystack, service, wallet, settings):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = service.initialize_deposit(wallet, 1000)['reference']
    paystack.add('GET', f'transaction/verify/{reference}', charge_data(reference, 100000))
    response = client.get('/wallet/callback/', {'reference': reference, 'trxref': reference})
    assert response.status_code == 200 and b'Payment successful' in response.content
    assert client.get('/wallet/callback/', {'reference': 'nope'}).status_code == 404

    settings.WALLET_CALLBACK_REDIRECT_URL = 'https://app.test/paid'
    redirect = client.get('/wallet/callback/', {'reference': reference})
    assert redirect.status_code == 302
    assert redirect['Location'] == f'https://app.test/paid?reference={reference}&status=success'


def test_admin_pages_render(client, staff_user, funded_wallet, bank_account, card):
    client.force_login(staff_user)
    for model in ('wallet', 'transaction', 'card', 'bank', 'bankaccount', 'settlement', 'settlementschedule',
                  'feeconfiguration', 'feehistory', 'webhookevent', 'webhookendpoint', 'webhookdeliveryattempt'):
        assert client.get(f'/admin/wallet/{model}/').status_code == 200, model
    assert client.get(f'/admin/wallet/wallet/{funded_wallet.pk}/change/').status_code == 200
    assert client.get('/admin/wallet/feeconfiguration/add/').status_code == 200


def test_admin_actions(client, staff_user, funded_wallet):
    client.force_login(staff_user)
    response = client.post('/admin/wallet/wallet/', {'action': 'lock_wallets', '_selected_action': [funded_wallet.pk]})
    assert response.status_code == 302
    funded_wallet.refresh_from_db()
    assert funded_wallet.is_locked
    csv = client.post('/admin/wallet/transaction/', {
        'action': 'export_csv', '_selected_action': list(Transaction.objects.values_list('pk', flat=True))})
    assert csv['Content-Type'] == 'text/csv'


def test_escrow_cancellation_is_staff_only(api_client, staff_client, funded_wallet, other_wallet):
    payment = api_client.post(f'{API}/wallets/me/pay/', {'amount': '3000', 'merchant': 'bola', 'escrow': True},
                              format='json').json()
    denied = api_client.post(f"{API}/transactions/{payment['id']}/cancel/")
    assert denied.status_code == 403
    cancelled = staff_client.post(f"{API}/transactions/{payment['id']}/cancel/", {'reason': 'dispute'}, format='json')
    assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)


def test_staff_can_release_any_escrow(api_client, staff_client, funded_wallet, other_wallet):
    payment = api_client.post(f'{API}/wallets/me/pay/', {'amount': '3000', 'merchant': 'bola', 'escrow': True},
                              format='json').json()
    other = APIClient()
    other.force_authenticate(other_wallet.user)
    assert other.post(f"{API}/transactions/{payment['id']}/release/").status_code == 404   # seller can't self-release
    assert staff_client.post(f"{API}/transactions/{payment['id']}/release/").json()['status'] == 'success'
