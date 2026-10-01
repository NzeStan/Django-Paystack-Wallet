"""
Settings for django-paystack-wallet.

Every setting can be supplied in three ways, checked in this order:

1. Your Django settings module, e.g. ``WALLET_ENABLE_FEES = True``
2. An environment variable with the same name, e.g. ``WALLET_ENABLE_FEES=true``
3. The package default defined in ``DEFAULTS`` below

Paystack credentials use their conventional names (``PAYSTACK_SECRET_KEY``,
``PAYSTACK_PUBLIC_KEY``, ...); every other setting is prefixed with ``WALLET_``.

Settings are resolved lazily on every access, so ``override_settings`` in tests
and environment changes are always honoured.

Usage::

    from wallet.conf import wallet_settings
    wallet_settings.CURRENCY

    # or, the older helper
    from wallet.conf import get_wallet_setting
    get_wallet_setting('CURRENCY')
"""
import json
import os
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


# Settings that are read from their bare name (no ``WALLET_`` prefix)
UNPREFIXED = {
    'PAYSTACK_SECRET_KEY',
    'PAYSTACK_PUBLIC_KEY',
    'PAYSTACK_API_URL',
    'PAYSTACK_TIMEOUT',
    'PAYSTACK_MAX_RETRIES',
}


DEFAULTS = {
    # ------------------------------------------------------------------
    # Paystack
    # ------------------------------------------------------------------
    'PAYSTACK_SECRET_KEY': '',
    'PAYSTACK_PUBLIC_KEY': '',
    'PAYSTACK_API_URL': 'https://api.paystack.co',
    'PAYSTACK_TIMEOUT': 30,
    # Retries apply to connection errors and 5xx responses on GET requests only;
    # POST requests are never retried automatically, to avoid double charges/transfers.
    'PAYSTACK_MAX_RETRIES': 2,

    # ------------------------------------------------------------------
    # Core wallet behaviour
    # ------------------------------------------------------------------
    'CURRENCY': 'NGN',
    # ISO 3166 alpha-2 code of your Paystack integration. Cards issued outside
    # this country are billed with international card fees.
    'COUNTRY': 'NG',
    'AUTO_CREATE_WALLET': True,
    'AUTO_CREATE_PAYSTACK_CUSTOMER': True,
    'USE_CELERY': False,

    # ------------------------------------------------------------------
    # Feature switches - turn off anything you do not need
    # ------------------------------------------------------------------
    'ENABLE_DEPOSITS': True,
    'ENABLE_WITHDRAWALS': True,
    'ENABLE_INTERNAL_TRANSFERS': True,
    'ENABLE_PAYMENTS': True,
    'ENABLE_CARDS': True,
    'ENABLE_CARD_REFUNDS': True,
    'ENABLE_DEDICATED_ACCOUNTS': True,
    'ENABLE_SETTLEMENTS': True,
    'ENABLE_WEBHOOK_FORWARDING': False,
    'ENABLE_RECIPIENT_LOOKUP': True,
    'SAVE_CARDS': True,

    # ------------------------------------------------------------------
    # Dedicated virtual accounts (DVA)
    # ------------------------------------------------------------------
    'AUTO_CREATE_DEDICATED_ACCOUNT': False,
    # e.g. 'wema-bank', 'titan-paystack'; use 'test-bank' with test keys
    'DEDICATED_ACCOUNT_PROVIDER': None,

    # ------------------------------------------------------------------
    # Limits (None means unlimited)
    # ------------------------------------------------------------------
    'MINIMUM_BALANCE': 0,
    'MINIMUM_TRANSACTION_AMOUNT': None,
    'MAXIMUM_TRANSACTION_AMOUNT': None,
    # Maximum total of outgoing money (withdrawals, transfers, payments) per day
    'MAXIMUM_DAILY_TRANSACTION': None,
    'MINIMUM_DEPOSIT_AMOUNT': 50,
    'MINIMUM_WITHDRAWAL_AMOUNT': 100,

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    'REQUIRE_TRANSACTION_PIN': False,
    'PIN_LENGTH': 4,
    'PIN_MAX_ATTEMPTS': 5,
    'PIN_LOCKOUT_MINUTES': 30,
    # Paystack webhook source IPs. Set WALLET_WEBHOOK_VERIFY_IP=True to enforce.
    'WEBHOOK_VERIFY_IP': False,
    'WEBHOOK_ALLOWED_IPS': ['52.31.139.75', '52.49.173.169', '52.214.14.220'],
    # Trust X-Forwarded-For when reading the client IP (only behind a trusted proxy)
    'TRUST_X_FORWARDED_FOR': False,
    # Rate limits per user (or IP when anonymous), using Django's cache. Use a shared
    # cache (Redis/Memcached) when you run more than one server.
    'ENABLE_THROTTLING': True,
    'THROTTLE_RATES': {
        'lookup': '20/min',      # recipient lookup (prevents phone-number enumeration)
        'pin': '5/min',          # setting/changing the PIN
        'money': '30/min',       # deposit, withdraw, transfer, pay, card charge, settlements
        'otp': '5/min',          # finalize withdrawal / resend OTP
        'resolve': '20/min',     # bank account name resolution & adding accounts
    },
    # Idempotency: clients send this header on POSTs that move money; retries with the
    # same key replay the first response instead of moving money twice.
    'IDEMPOTENCY_HEADER': 'Idempotency-Key',
    'REQUIRE_IDEMPOTENCY_KEY': False,
    'IDEMPOTENCY_TTL_HOURS': 24,
    # Audit log of staff actions (refunds, reversals, escrow decisions, locks)
    'AUDIT_LOGGER': 'wallet.audit',

    # ------------------------------------------------------------------
    # Phone numbers & internal transfer recipient lookup
    # ------------------------------------------------------------------
    # Dotted attribute path on your user model that holds the phone number,
    # e.g. 'phone' or 'profile.phone_number'. Copied onto the wallet on creation.
    'USER_PHONE_FIELD': None,
    'PHONE_DEFAULT_COUNTRY_CODE': '234',
    # Dotted path to a callable(str) -> str to replace the built-in normaliser
    'PHONE_NUMBER_NORMALIZER': None,
    # How an internal transfer recipient may be identified
    'TRANSFER_RECIPIENT_LOOKUP_FIELDS': ['id', 'tag', 'phone_number', 'email'],

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------
    'ENABLE_FEES': False,
    # Dotted path to a FeeCalculator subclass for fully custom pricing
    'FEE_CALCULATOR': 'wallet.services.fee_service.FeeCalculator',
    # Look up FeeConfiguration rows in the database before falling back to settings
    'USE_DATABASE_FEE_CONFIG': False,
    # Bearer options: 'customer', 'merchant', 'platform', 'split'
    'DEFAULT_FEE_BEARER': 'platform',
    'DEPOSIT_FEE_BEARER': None,
    'WITHDRAWAL_FEE_BEARER': 'customer',
    'TRANSFER_FEE_BEARER': None,
    'PAYMENT_FEE_BEARER': None,
    'DVA_FEE_BEARER': 'merchant',
    # Allow API clients to choose who bears the fee. Keep this off unless you
    # validate the choice yourself - otherwise users can opt out of fees.
    'ALLOW_FEE_BEARER_OVERRIDE': False,
    # When the customer bears a deposit fee, gross the charge up so the wallet
    # receives exactly the requested amount after Paystack takes its cut.
    'DEPOSIT_FEE_GROSS_UP': True,
    'ENABLE_DEPOSIT_FEES': True,

    # Local card / bank / USSD / QR (Paystack Nigeria: 1.5% + NGN 100, capped at NGN 2,000,
    # NGN 100 waived under NGN 2,500)
    'LOCAL_CARD_PERCENTAGE_FEE': Decimal('1.5'),
    'LOCAL_CARD_FLAT_FEE': Decimal('100'),
    'LOCAL_CARD_FEE_CAP': Decimal('2000'),
    'LOCAL_CARD_FEE_WAIVER_THRESHOLD': Decimal('2500'),

    # International cards (3.9% + NGN 100)
    'INTL_CARD_PERCENTAGE_FEE': Decimal('3.9'),
    'INTL_CARD_FLAT_FEE': Decimal('100'),
    'INTL_CARD_FEE_CAP': None,

    # Dedicated virtual accounts / bank transfer (1% capped at NGN 300)
    'DVA_PERCENTAGE_FEE': Decimal('1.0'),
    'DVA_FLAT_FEE': Decimal('0'),
    'DVA_FEE_CAP': Decimal('300'),

    # Mobile money (Ghana/Kenya)
    'MOBILE_MONEY_PERCENTAGE_FEE': Decimal('1.95'),
    'MOBILE_MONEY_FLAT_FEE': Decimal('0'),
    'MOBILE_MONEY_FEE_CAP': None,

    # Withdrawals to bank (Paystack transfer pricing)
    'ENABLE_TRANSFER_FEES': True,
    'TRANSFER_FEE_TIERS': [
        {'max_amount': 5000, 'fee': 10},
        {'max_amount': 50000, 'fee': 25},
        {'max_amount': None, 'fee': 50},
    ],

    # Wallet-to-wallet transfers (your own pricing; Paystack charges nothing)
    'ENABLE_INTERNAL_TRANSFER_FEES': False,
    'INTERNAL_TRANSFER_PERCENTAGE_FEE': Decimal('0'),
    'INTERNAL_TRANSFER_FLAT_FEE': Decimal('0'),
    'INTERNAL_TRANSFER_FEE_CAP': None,

    # Wallet payments / marketplace commission (your own pricing)
    'ENABLE_PAYMENT_FEES': False,
    'PAYMENT_PERCENTAGE_FEE': Decimal('0'),
    'PAYMENT_FLAT_FEE': Decimal('0'),
    'PAYMENT_FEE_CAP': None,

    # Split bearer ratio (must sum to 100)
    'FEE_SPLIT_CUSTOMER_PERCENTAGE': Decimal('50'),
    'FEE_SPLIT_MERCHANT_PERCENTAGE': Decimal('50'),

    # Educational institution pricing (0.7% capped at NGN 1,500)
    'ENABLE_EDUCATIONAL_PRICING': False,
    'EDUCATIONAL_CARD_PERCENTAGE_FEE': Decimal('0.7'),
    'EDUCATIONAL_CARD_FEE_CAP': Decimal('1500'),

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------
    'AUTO_SETTLEMENT': False,

    # ------------------------------------------------------------------
    # Pluggable integrations
    # ------------------------------------------------------------------
    # List of dotted paths to notification backends, e.g.
    # ['wallet.notifications.backends.EmailNotificationBackend']
    'NOTIFICATION_BACKENDS': [],
    'EMAIL_SENDER': None,

    # ------------------------------------------------------------------
    # Deposits / callback
    # ------------------------------------------------------------------
    # Default callback_url sent to Paystack when a deposit is initialised
    'DEFAULT_CALLBACK_URL': None,
    # Where the built-in callback view redirects after verifying a payment.
    # ``?reference=...&status=...`` is appended. Leave empty to render a template.
    'CALLBACK_REDIRECT_URL': None,
    # Payment channels offered on Paystack checkout (None = all enabled on your integration)
    'PAYMENT_CHANNELS': None,
    # Pending deposits/withdrawals older than this are reconciled with Paystack
    'RECONCILE_AFTER_MINUTES': 10,
    # How many pending transactions one reconciliation run checks (per type)
    'RECONCILE_BATCH_SIZE': 500,

    # ------------------------------------------------------------------
    # Data retention (manage.py prune_wallet_data / prune_wallet_data_task)
    # ------------------------------------------------------------------
    # Processed webhook events and delivery attempts older than this are deleted
    # (None = keep forever). Ledger data (transactions) is never pruned.
    'WEBHOOK_RETENTION_DAYS': 90,
    # Failed outbound deliveries older than this are no longer retried
    'WEBHOOK_RETRY_WINDOW_HOURS': 72,

    # ------------------------------------------------------------------
    # REST API
    # ------------------------------------------------------------------
    'API_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'API_PAGE_SIZE': 20,
    'API_MAX_PAGE_SIZE': 100,

    # ------------------------------------------------------------------
    # Banks & exports
    # ------------------------------------------------------------------
    'AUTO_SYNC_BANKS': False,
    'BANK_COUNTRY': 'nigeria',
    'EXPORT_PAGESIZE': 'A4',
    'EXPORT_ORIENTATION': 'portrait',
}


# Settings removed in 1.0 - kept here only to give a helpful error message.
REMOVED_SETTINGS = {
    'USE_UUID': 'Wallet models always use UUID primary keys.',
    'SEND_EMAIL_NOTIFICATIONS': 'Configure WALLET_NOTIFICATION_BACKENDS instead.',
    'USER_MODEL': 'The wallet always uses settings.AUTH_USER_MODEL.',
}


_TRUE = {'1', 'true', 'yes', 'on', 'y', 't'}
_FALSE = {'0', 'false', 'no', 'off', 'n', 'f', ''}


def setting_name(name):
    """Return the Django settings / environment variable name for a wallet setting."""
    return name if name in UNPREFIXED else f'WALLET_{name}'


def _parse_env(raw, default):
    """Coerce an environment variable string to the type of the default value."""
    value = raw.strip()

    # ``WALLET_X=`` (empty) means "not set": use the default
    if value == '':
        return default

    if isinstance(default, bool):
        lowered = value.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ImproperlyConfigured(f"Expected a boolean value, got {raw!r}")

    if isinstance(default, int):
        return int(value)

    if isinstance(default, Decimal):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ImproperlyConfigured(f"Expected a decimal value, got {raw!r}") from exc

    if isinstance(default, (list, tuple, dict)):
        if value.startswith(('[', '{')):
            return json.loads(value)
        if isinstance(default, dict):
            raise ImproperlyConfigured(f"Expected a JSON object, got {raw!r}")
        return [item.strip() for item in value.split(',') if item.strip()]

    if value.lower() in ('none', 'null'):
        return None

    # Unset-by-default settings (e.g. limits, dotted paths): accept numbers and
    # JSON lists/objects, otherwise keep the raw string.
    if default is None:
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if isinstance(parsed, bool):
            return parsed
        if isinstance(parsed, (int, float)):
            return Decimal(value)
        return parsed
    return value


class WalletSettings:
    """
    Lazy accessor for wallet settings.

    ``wallet_settings.NAME`` resolves Django settings, then environment variables,
    then defaults - on every access.
    """

    def __init__(self, defaults=None):
        self.defaults = defaults or DEFAULTS

    def __getattr__(self, name):
        if name.startswith('_') or name == 'defaults':
            raise AttributeError(name)
        return self.get(name)

    def get(self, name):
        if name in REMOVED_SETTINGS and name not in self.defaults:
            raise ImproperlyConfigured(
                f"Setting {setting_name(name)} has been removed: {REMOVED_SETTINGS[name]}"
            )
        if name not in self.defaults:
            raise AttributeError(f"Unknown wallet setting: {name}")

        full_name = setting_name(name)
        default = self.defaults[name]

        if hasattr(django_settings, full_name):
            return getattr(django_settings, full_name)

        raw = os.environ.get(full_name)
        if raw is not None:
            return _parse_env(raw, default)

        # Deep-copy mutable defaults so callers can't mutate the module-level dict
        if isinstance(default, list):
            return [dict(item) if isinstance(item, dict) else item for item in default]
        if isinstance(default, dict):
            return dict(default)
        return default

    def as_dict(self):
        """Return every resolved setting (secret keys masked) - useful for debugging."""
        resolved = {}
        for name in self.defaults:
            value = self.get(name)
            if 'SECRET' in name and value:
                value = f"{value[:7]}...{value[-4:]}" if len(value) > 12 else '***'
            resolved[name] = value
        return resolved

    def import_from(self, name):
        """Import the object referenced by a dotted-path setting (None if unset)."""
        path = self.get(name)
        if not path:
            return None
        if not isinstance(path, str):
            return path
        try:
            return import_string(path)
        except ImportError as exc:
            raise ImproperlyConfigured(
                f"Could not import {path!r} for setting {setting_name(name)}: {exc}"
            ) from exc

    def import_list(self, name):
        """Import each dotted path in a list setting."""
        return [import_string(path) if isinstance(path, str) else path for path in (self.get(name) or [])]


wallet_settings = WalletSettings()


def get_wallet_setting(name):
    """Return a single wallet setting (kept for backwards compatibility)."""
    try:
        return wallet_settings.get(name)
    except AttributeError as exc:
        raise ValueError(str(exc)) from exc


def load_env_file(path='.env', override=False):
    """
    Load ``KEY=VALUE`` lines from a ``.env`` file into ``os.environ``.

    Call it at the top of your ``settings.py`` (safe to import there - it does
    not touch Django settings)::

        from wallet.conf import load_env_file
        load_env_file(BASE_DIR / '.env')

    Existing environment variables win unless ``override=True`` (so real
    deployment variables are never replaced by a stray file). Returns the
    number of variables set; a missing file is ignored.
    """
    try:
        with open(path, encoding='utf-8') as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return 0

    loaded = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[len('export '):]
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        elif ' #' in value:
            value = value.split(' #', 1)[0].rstrip()
        if not key or (key in os.environ and not override):
            continue
        os.environ[key] = value
        loaded += 1
    return loaded


def is_feature_enabled(feature):
    """Return True if ``WALLET_ENABLE_<FEATURE>`` is on, e.g. ``is_feature_enabled('WITHDRAWALS')``."""
    return bool(wallet_settings.get(f'ENABLE_{feature.upper()}'))
