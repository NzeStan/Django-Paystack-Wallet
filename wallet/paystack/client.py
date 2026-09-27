"""
HTTP client for the Paystack API.

    from wallet.paystack import PaystackClient

    paystack = PaystackClient()                      # uses PAYSTACK_SECRET_KEY
    paystack.transactions.initialize(email='a@b.com', amount=500000)
    paystack.transfers.verify('trf-ref')
    for customer in paystack.paginate('customer'):   # walk every page
        ...

Every resource method returns the ``data`` part of Paystack's response. Use
``paystack.request(..., raw=True)`` when you need ``meta`` or ``message`` too.
"""
import hashlib
import hmac
import logging
import time

import requests

from wallet.conf import wallet_settings
from wallet.exceptions import (
    InvalidPaystackResponse,
    PaystackAPIError,
    PaystackConfigurationError,
)
from wallet.paystack import resources

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def clean_params(params):
    """Drop None values so optional arguments are not sent to Paystack."""
    return {key: value for key, value in (params or {}).items() if value is not None}


def compute_signature(payload, secret_key=None):
    """HMAC-SHA512 hex digest of ``payload`` (bytes) keyed by the secret key."""
    key = (secret_key or wallet_settings.PAYSTACK_SECRET_KEY or '').encode('utf-8')
    return hmac.new(key, payload, hashlib.sha512).hexdigest()


def verify_signature(payload, signature, secret_key=None):
    """Constant-time check of an ``X-Paystack-Signature`` header."""
    if not signature or payload is None:
        return False
    return hmac.compare_digest(compute_signature(payload, secret_key), str(signature))


class PaystackClient:
    """Thin, well-behaved wrapper around the Paystack REST API."""

    def __init__(self, secret_key=None, base_url=None, timeout=None, max_retries=None, session=None):
        self._secret_key = secret_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self.session = session or requests.Session()

        self.transactions = resources.Transactions(self)
        self.splits = resources.TransactionSplits(self)
        self.terminals = resources.Terminals(self)
        self.virtual_terminals = resources.VirtualTerminals(self)
        self.customers = resources.Customers(self)
        self.direct_debit = resources.DirectDebit(self)
        self.dedicated_accounts = resources.DedicatedAccounts(self)
        self.apple_pay = resources.ApplePay(self)
        self.subaccounts = resources.Subaccounts(self)
        self.plans = resources.Plans(self)
        self.subscriptions = resources.Subscriptions(self)
        self.products = resources.Products(self)
        self.payment_pages = resources.PaymentPages(self)
        self.payment_requests = resources.PaymentRequests(self)
        self.settlements = resources.Settlements(self)
        self.transfer_recipients = resources.TransferRecipients(self)
        self.transfers = resources.Transfers(self)
        self.transfer_control = resources.TransferControl(self)
        self.bulk_charges = resources.BulkCharges(self)
        self.integration = resources.Integration(self)
        self.charges = resources.Charges(self)
        self.disputes = resources.Disputes(self)
        self.refunds = resources.Refunds(self)
        self.verification = resources.Verification(self)
        self.misc = resources.Miscellaneous(self)

    # ------------------------------------------------------------------
    # Configuration (resolved lazily so settings overrides are honoured)
    # ------------------------------------------------------------------

    @property
    def secret_key(self):
        return self._secret_key or wallet_settings.PAYSTACK_SECRET_KEY

    @property
    def public_key(self):
        return wallet_settings.PAYSTACK_PUBLIC_KEY

    @property
    def base_url(self):
        return (self._base_url or wallet_settings.PAYSTACK_API_URL).rstrip('/')

    @property
    def timeout(self):
        return self._timeout or wallet_settings.PAYSTACK_TIMEOUT

    @property
    def max_retries(self):
        return self._max_retries if self._max_retries is not None else wallet_settings.PAYSTACK_MAX_RETRIES

    @property
    def is_test_mode(self):
        return str(self.secret_key or '').startswith('sk_test_')

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _headers(self):
        if not self.secret_key:
            raise PaystackConfigurationError()
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'django-paystack-wallet',
        }

    def request(self, method, path, params=None, json=None, raw=False):
        """
        Call ``{base_url}/{path}`` and return ``data`` (or the full body when ``raw``).

        GET requests are retried on connection errors and 429/5xx responses.
        Other methods are never retried: a timed-out POST may still have
        succeeded on Paystack's side and must be reconciled instead.
        """
        method = method.upper()
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = self._headers()
        attempts = 1 + (int(self.max_retries) if method == 'GET' else 0)
        params = clean_params(params) if params else None
        json = clean_params(json) if isinstance(json, dict) else json

        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(
                    method, url, headers=headers, params=params, json=json, timeout=self.timeout,
                )
            except requests.RequestException as exc:
                logger.warning("Paystack %s %s failed (attempt %s/%s): %s", method, path, attempt, attempts, exc)
                last_error = PaystackAPIError(message=str(exc))
                if attempt < attempts:
                    time.sleep(min(2 ** (attempt - 1) * 0.5, 4))
                    continue
                raise last_error from exc

            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                logger.warning("Paystack %s %s returned %s, retrying", method, path, response.status_code)
                time.sleep(min(2 ** (attempt - 1) * 0.5, 4))
                continue

            return self._handle_response(response, method, path, raw)

        raise last_error  # pragma: no cover - loop always returns or raises

    def _handle_response(self, response, method, path, raw):
        if response.status_code == 204 or not response.content:
            return {} if not raw else {'status': True, 'data': {}}

        try:
            body = response.json()
        except ValueError:
            logger.error("Paystack %s %s returned non-JSON (%s)", method, path, response.status_code)
            raise InvalidPaystackResponse(response.text[:500], status_code=response.status_code)

        if response.status_code >= 400 or not body.get('status', False):
            message = body.get('message') or 'Unknown Paystack error'
            logger.info("Paystack %s %s rejected (%s): %s", method, path, response.status_code, message)
            raise PaystackAPIError(message=message, status_code=response.status_code, response=body)

        return body if raw else body.get('data', {})

    def get(self, path, **params):
        return self.request('GET', path, params=params)

    def post(self, path, data=None, **params):
        return self.request('POST', path, params=params or None, json=data or {})

    def put(self, path, data=None):
        return self.request('PUT', path, json=data or {})

    def delete(self, path, data=None):
        return self.request('DELETE', path, json=data)

    def paginate(self, path, params=None, per_page=100, max_pages=None):
        """Yield every item of a paginated list endpoint."""
        page = 1
        params = dict(params or {})
        while True:
            body = self.request('GET', path, params={**params, 'perPage': per_page, 'page': page}, raw=True)
            items = body.get('data') or []
            yield from items
            meta = body.get('meta') or {}
            page_count = meta.get('pageCount') or 0
            if not items or page >= page_count or (max_pages and page >= max_pages):
                return
            page += 1

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def verify_webhook_signature(self, signature, payload):
        """Return True if ``signature`` matches ``payload``; raise InvalidWebhookSignature otherwise."""
        from wallet.exceptions import InvalidWebhookSignature

        if not verify_signature(payload, signature, self.secret_key):
            raise InvalidWebhookSignature()
        return True

    # ------------------------------------------------------------------
    # Convenience aliases for the most common calls (older API)
    # ------------------------------------------------------------------

    def initialize_transaction(self, amount, email, **kwargs):
        return self.transactions.initialize(amount=amount, email=email, **kwargs)

    def verify_transaction(self, reference):
        return self.transactions.verify(reference)

    def charge_authorization(self, amount, email, authorization_code, **kwargs):
        return self.transactions.charge_authorization(
            amount=amount, email=email, authorization_code=authorization_code, **kwargs
        )

    def create_customer(self, email, **kwargs):
        return self.customers.create(email=email, **kwargs)

    def create_dedicated_account(self, customer, **kwargs):
        return self.dedicated_accounts.create(customer=customer, **kwargs)

    def create_transfer_recipient(self, account_type, name, account_number=None, bank_code=None, **kwargs):
        return self.transfer_recipients.create(
            type=account_type, name=name, account_number=account_number, bank_code=bank_code, **kwargs
        )

    def initiate_transfer(self, amount, recipient_code, reference=None, reason=None, currency=None):
        return self.transfers.initiate(
            amount=amount, recipient=recipient_code, reference=reference, reason=reason, currency=currency,
        )

    def finalize_transfer(self, transfer_code, otp):
        return self.transfers.finalize(transfer_code=transfer_code, otp=otp)

    def verify_transfer(self, reference):
        return self.transfers.verify(reference)

    def resolve_account_number(self, account_number, bank_code):
        return self.verification.resolve_account(account_number=account_number, bank_code=bank_code)

    def list_banks(self, country=None, currency=None, **kwargs):
        return self.misc.list_banks(country=country, currency=currency, **kwargs)

    def check_balance(self):
        return self.transfer_control.balance()


_default_client = None


def get_paystack_client():
    """Shared client instance (resolves settings lazily, safe to reuse)."""
    global _default_client
    if _default_client is None:
        _default_client = PaystackClient()
    return _default_client
