import json
from decimal import Decimal

import pytest
import responses as responses_lib
from djmoney.money import Money
from rest_framework.test import APIClient

from wallet.models import Bank, BankAccount, Card
from wallet.paystack.client import compute_signature
from wallet.services.wallet_service import WalletService

PAYSTACK_BASE = 'https://api.paystack.co'


class PaystackMock:
    """Registers fake Paystack HTTP responses and inspects the requests we sent."""

    def __init__(self, rsps):
        self.rsps = rsps

    def add(self, method, path, data=None, status=200, message='ok', ok=True, body=None, meta=None):
        if body is None:
            body = {'status': ok, 'message': message, 'data': {} if data is None else data}
            if meta is not None:
                body['meta'] = meta
        self.rsps.add(method, f"{PAYSTACK_BASE}/{path.lstrip('/')}", json=body, status=status)

    def error(self, method, path, message='Bad request', status=400):
        self.add(method, path, status=status, ok=False, message=message)

    def calls(self, path=None, method=None):
        result = []
        for call in self.rsps.calls:
            url = call.request.url.split('?')[0]
            if path is not None and not url.endswith('/' + path.lstrip('/')):
                continue
            if method is not None and call.request.method != method:
                continue
            result.append(call)
        return result

    def last_body(self, path=None):
        call = self.calls(path)[-1]
        return json.loads(call.request.body) if call.request.body else {}


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Rate-limit counters live in the cache; start every test from zero."""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def paystack():
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield PaystackMock(rsps)


@pytest.fixture
def service():
    return WalletService()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username='ada', email='ada@example.com', first_name='Ada', last_name='Obi',
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        username='bola', email='bola@example.com', first_name='Bola', last_name='Ade',
    )


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username='staff', email='staff@example.com', is_staff=True, is_superuser=True,
    )


@pytest.fixture
def wallet(user, service):
    return service.get_wallet(user)


@pytest.fixture
def other_wallet(other_user, service):
    return service.get_wallet(other_user)


def fund(wallet, amount):
    """Give a wallet money through the ledger (a direct credit)."""
    WalletService().credit_wallet(wallet, Decimal(str(amount)), description='test funding')
    wallet.refresh_from_db()
    return wallet


@pytest.fixture
def funded_wallet(wallet):
    return fund(wallet, 100000)


@pytest.fixture
def bank(db):
    return Bank.objects.create(name='Test Bank', code='058', slug='test-bank', currency='NGN', type='nuban')


@pytest.fixture
def bank_account(wallet, bank):
    return BankAccount.objects.create(
        wallet=wallet, bank=bank, account_number='0123456789', account_name='ADA OBI', is_verified=True,
        is_default=True, paystack_recipient_code='RCP_test123',
    )


@pytest.fixture
def card(wallet):
    return Card.objects.create(
        wallet=wallet, card_type='visa', last_four='4081', expiry_month='12', expiry_year='2099', bin='408408',
        country_code='NG', email='ada@example.com', paystack_authorization_code='AUTH_abc123',
        paystack_authorization_signature='SIG_abc', is_default=True,
    )


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def staff_client(staff_user):
    client = APIClient()
    client.force_authenticate(user=staff_user)
    return client


def webhook_request(client, payload, secret=None, **extra):
    from django.conf import settings

    body = json.dumps(payload).encode()
    signature = compute_signature(body, secret or settings.PAYSTACK_SECRET_KEY)
    return client.post('/wallet/webhook/', data=body, content_type='application/json',
                       HTTP_X_PAYSTACK_SIGNATURE=signature, **extra)


def charge_data(reference, amount_kobo, channel='card', status='success', customer=None, authorization=None,
                currency='NGN', **extra):
    data = {
        'id': 1234567, 'reference': reference, 'amount': amount_kobo, 'currency': currency, 'status': status,
        'channel': channel, 'gateway_response': 'Successful' if status == 'success' else 'Declined',
        'paid_at': '2026-09-27T10:00:00.000Z', 'customer': customer or {'email': 'ada@example.com'},
        'authorization': authorization if authorization is not None else {
            'authorization_code': 'AUTH_new', 'bin': '408408', 'last4': '4081', 'exp_month': '12',
            'exp_year': '2099', 'channel': 'card', 'card_type': 'visa ', 'bank': 'TEST BANK',
            'country_code': 'NG', 'brand': 'visa', 'reusable': True, 'signature': 'SIG_new',
            'account_name': None,
        },
    }
    data.update(extra)
    return data


def money(amount, currency='NGN'):
    return Money(Decimal(str(amount)), currency)
