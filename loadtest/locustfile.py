"""
HTTP load test for a project that includes ``wallet.urls``.

    pip install locust
    LOADTEST_TOKENS=tok1,tok2,tok3 LOADTEST_RECIPIENTS=ada,bola,chi \
        locust -f loadtest/locustfile.py --host https://staging.example.com

* ``LOADTEST_TOKENS``      - comma separated API tokens of pre-funded test users
* ``LOADTEST_AUTH_SCHEME`` - ``Token`` (DRF TokenAuthentication, default) or ``Bearer`` (JWT)
* ``LOADTEST_RECIPIENTS``  - wallet tags/phones to send money to
* ``LOADTEST_PREFIX``      - URL prefix where wallet.urls is included (default ``/wallet``)

Run it against STAGING with Paystack TEST keys - it only calls endpoints that do
not reach Paystack (balance, history, lookup, internal transfers, fee quotes).
Raise ``WALLET_THROTTLE_RATES`` on staging first, or you will mostly measure 429s.
"""
import itertools
import os
import random
import uuid

from locust import HttpUser, between, task

TOKENS = [t.strip() for t in os.environ.get('LOADTEST_TOKENS', '').split(',') if t.strip()]
RECIPIENTS = [r.strip() for r in os.environ.get('LOADTEST_RECIPIENTS', '').split(',') if r.strip()]
SCHEME = os.environ.get('LOADTEST_AUTH_SCHEME', 'Token')
PREFIX = os.environ.get('LOADTEST_PREFIX', '/wallet').rstrip('/')
_tokens = itertools.cycle(TOKENS or ['missing-token'])


class WalletUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        self.client.headers['Authorization'] = f"{SCHEME} {next(_tokens)}"

    @task(10)
    def balance(self):
        self.client.get(f"{PREFIX}/api/wallets/me/balance/", name='balance')

    @task(6)
    def history(self):
        self.client.get(f"{PREFIX}/api/wallets/me/transactions/?page_size=20", name='transactions')

    @task(2)
    def fee_quote(self):
        self.client.post(f"{PREFIX}/api/wallets/fee-quote/",
                         json={'amount': '5000', 'transaction_type': 'withdrawal'}, name='fee-quote')

    @task(2)
    def lookup(self):
        if RECIPIENTS:
            self.client.get(f"{PREFIX}/api/wallets/lookup/?recipient={random.choice(RECIPIENTS)}", name='lookup')

    @task(3)
    def transfer(self):
        if not RECIPIENTS:
            return
        key = str(uuid.uuid4())
        with self.client.post(
            f"{PREFIX}/api/wallets/me/transfer/",
            json={'recipient': random.choice(RECIPIENTS), 'amount': '1.00', 'description': 'load test'},
            headers={'Idempotency-Key': key}, name='transfer', catch_response=True,
        ) as response:
            # Sending to yourself or running dry are expected business outcomes, not failures
            if response.status_code in (201, 400):
                response.success()
