# Configuration

Every setting can be provided three ways, checked in this order:

1. **Django settings**: `WALLET_ENABLE_FEES = True`
2. **Environment variable** with the same name: `WALLET_ENABLE_FEES=true`
3. **Package default** (shown below)

Paystack credentials use their usual names (`PAYSTACK_SECRET_KEY`, …); everything
else is prefixed with `WALLET_`. Settings are read on every access, so
`override_settings` in tests and environment changes both work.

Environment values are converted to the default's type: booleans accept
`true/false/1/0/yes/no/on/off`, lists accept `a,b,c` or JSON, dicts/lists of dicts
accept JSON, and an **empty value means "use the default"**. `.env.example` lists every
variable.

```bash
python manage.py wallet_settings          # what is in effect (secrets masked)
python manage.py wallet_settings --json
```

In code:

```python
from wallet.conf import wallet_settings, is_feature_enabled

wallet_settings.CURRENCY
is_feature_enabled('WITHDRAWALS')
```

## Paystack

| Setting | Default | Notes |
| --- | --- | --- |
| `PAYSTACK_SECRET_KEY` | `''` | **Required.** Also used to verify webhook signatures |
| `PAYSTACK_PUBLIC_KEY` | `''` | Returned by the deposit endpoint for Paystack InlineJS |
| `PAYSTACK_API_URL` | `https://api.paystack.co` | |
| `PAYSTACK_TIMEOUT` | `30` | Seconds |
| `PAYSTACK_MAX_RETRIES` | `2` | GET requests only; charges and transfers are never retried automatically |

## Core

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_CURRENCY` | `NGN` | Currency of new wallets. Changing it never creates migrations |
| `WALLET_COUNTRY` | `NG` | Your integration's country; cards issued elsewhere get international pricing |
| `WALLET_AUTO_CREATE_WALLET` | `True` | Create a wallet when a user is created |
| `WALLET_AUTO_CREATE_PAYSTACK_CUSTOMER` | `True` | Create the Paystack customer for new wallets |
| `WALLET_USE_CELERY` | `False` | Process webhooks, provisioning and deliveries on Celery |

## Feature switches

Turning a feature off disables its service methods (they raise `FeatureDisabled`) and
its API endpoints (HTTP 403).

| Setting | Default |
| --- | --- |
| `WALLET_ENABLE_DEPOSITS` | `True` |
| `WALLET_ENABLE_WITHDRAWALS` | `True` |
| `WALLET_ENABLE_INTERNAL_TRANSFERS` | `True` |
| `WALLET_ENABLE_PAYMENTS` | `True` |
| `WALLET_ENABLE_CARDS` | `True` |
| `WALLET_ENABLE_CARD_REFUNDS` | `True` |
| `WALLET_ENABLE_DEDICATED_ACCOUNTS` | `True` |
| `WALLET_ENABLE_SETTLEMENTS` | `True` |
| `WALLET_ENABLE_RECIPIENT_LOOKUP` | `True` |
| `WALLET_ENABLE_WEBHOOK_FORWARDING` | `False` |
| `WALLET_SAVE_CARDS` | `True` (save reusable card authorizations after card payments) |

## Dedicated virtual accounts

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_AUTO_CREATE_DEDICATED_ACCOUNT` | `False` | Create a DVA for every new wallet (and after identity validation succeeds) |
| `WALLET_DEDICATED_ACCOUNT_PROVIDER` | `None` | Preferred bank slug, e.g. `wema-bank`, `titan-paystack`; `test-bank` in test mode |

Most Nigerian businesses must validate a customer's identity before Paystack issues a
DVA. Use `WalletService().validate_customer(...)` (or `POST /wallets/me/validate-customer/`);
the result arrives by webhook.

## Limits

`None`/empty means unlimited. Limits apply to money leaving a wallet (withdrawals,
transfers, payments), checked while the wallet row is locked.

| Setting | Default |
| --- | --- |
| `WALLET_MINIMUM_BALANCE` | `0` |
| `WALLET_MINIMUM_TRANSACTION_AMOUNT` | `None` |
| `WALLET_MAXIMUM_TRANSACTION_AMOUNT` | `None` |
| `WALLET_MAXIMUM_DAILY_TRANSACTION` | `None` (per wallet per day; pending withdrawals count) |
| `WALLET_MINIMUM_DEPOSIT_AMOUNT` | `50` |
| `WALLET_MINIMUM_WITHDRAWAL_AMOUNT` | `100` |

A single wallet can get its own daily limit via `Wallet.daily_limit` (for example for
KYC tiers).

## Security

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_REQUIRE_TRANSACTION_PIN` | `False` | API requires `pin` for withdraw, transfer, pay, card charge, settlements |
| `WALLET_PIN_LENGTH` | `4` | |
| `WALLET_PIN_MAX_ATTEMPTS` | `5` | Then the PIN locks |
| `WALLET_PIN_LOCKOUT_MINUTES` | `30` | |
| `WALLET_WEBHOOK_VERIFY_IP` | `False` | Also reject webhooks not from Paystack's IPs |
| `WALLET_WEBHOOK_ALLOWED_IPS` | Paystack's 3 IPs | |
| `WALLET_TRUST_X_FORWARDED_FOR` | `False` | Only behind a proxy you control |
| `WALLET_ENABLE_THROTTLING` | `True` | Per-user rate limits (per IP when anonymous) |
| `WALLET_THROTTLE_RATES` | `lookup 20/min`, `pin 5/min`, `money 30/min`, `otp 5/min`, `resolve 20/min` | JSON in env, e.g. `{"money": "60/min"}` (replaces the whole dict) |
| `WALLET_IDEMPOTENCY_HEADER` | `Idempotency-Key` | |
| `WALLET_REQUIRE_IDEMPOTENCY_KEY` | `False` | Reject money-moving POSTs without a key |
| `WALLET_IDEMPOTENCY_TTL_HOURS` | `24` | How long a key's response is remembered |
| `WALLET_AUDIT_LOGGER` | `wallet.audit` | Logger receiving JSON audit events |

PINs are hashed with Django's password hashers. Signatures are always verified.

Rate limits are counted in Django's cache. With more than one server, use a shared
cache (Redis/Memcached) or each server counts separately. Rate-limit scopes:

| Scope | Endpoints |
| --- | --- |
| `lookup` | recipient lookup (stops phone-number enumeration) |
| `pin` | set/change PIN |
| `money` | deposit, charge card, withdraw, transfer, pay, create settlement |
| `otp` | finalize withdrawal/settlement, resend OTP |
| `resolve` | resolve bank account, add bank account, identity validation |

Audit events are one JSON object per line, for example
`{"action": "transaction.reverse", "performed_by": "12", "transaction": "TRF-…", "reason": "fraud"}`.
Actions: `refund.create`, `transaction.reverse`, `escrow.release`, `escrow.cancel`,
`deposit.cancel`, `wallet.lock`, `wallet.unlock`. The acting user is also stored in the
affected transaction's `metadata`. Send the logger somewhere durable:

```python
LOGGING = {
    'version': 1,
    'handlers': {'audit': {'class': 'logging.FileHandler', 'filename': '/var/log/wallet-audit.log'}},
    'loggers': {'wallet.audit': {'handlers': ['audit'], 'level': 'INFO', 'propagate': False}},
}
```

## Phone numbers & recipients

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_USER_PHONE_FIELD` | `None` | Attribute path on your user, e.g. `phone` or `profile.phone_number`, copied to the wallet on creation |
| `WALLET_PHONE_DEFAULT_COUNTRY_CODE` | `234` | Used to turn `0803…` into `+234803…` |
| `WALLET_PHONE_NUMBER_NORMALIZER` | `None` | Dotted path to your own `callable(str) -> str` (e.g. built on `phonenumbers`) |
| `WALLET_TRANSFER_RECIPIENT_LOOKUP_FIELDS` | `['id', 'tag', 'phone_number', 'email']` | Remove entries to forbid a lookup method |

## Fees

Fees are off until `WALLET_ENABLE_FEES=true`. See [usage → fees](usage.md#fees) for the
concepts.

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_ENABLE_FEES` | `False` | Master switch |
| `WALLET_FEE_CALCULATOR` | `wallet.services.fee_service.FeeCalculator` | Replace pricing entirely |
| `WALLET_USE_DATABASE_FEE_CONFIG` | `False` | Use `FeeConfiguration` rows (admin-editable) first |
| `WALLET_DEFAULT_FEE_BEARER` | `platform` | `customer`, `merchant`, `platform` or `split` |
| `WALLET_DEPOSIT_FEE_BEARER` | `None` (→ default) | |
| `WALLET_WITHDRAWAL_FEE_BEARER` | `customer` | The wallet owner pays on top |
| `WALLET_TRANSFER_FEE_BEARER` | `None` (→ default) | |
| `WALLET_PAYMENT_FEE_BEARER` | `None` (→ default) | |
| `WALLET_DVA_FEE_BEARER` | `merchant` | Bank-transfer deposits: deducted from the credited amount |
| `WALLET_ALLOW_FEE_BEARER_OVERRIDE` | `False` | Let API clients choose the bearer (staff always can) |
| `WALLET_DEPOSIT_FEE_GROSS_UP` | `True` | Customer-borne deposit fees cover Paystack's cut exactly |
| `WALLET_ENABLE_DEPOSIT_FEES` | `True` | |
| `WALLET_ENABLE_TRANSFER_FEES` | `True` | Withdrawals to bank |
| `WALLET_ENABLE_INTERNAL_TRANSFER_FEES` | `False` | Wallet-to-wallet |
| `WALLET_ENABLE_PAYMENT_FEES` | `False` | Marketplace commission |

Pricing (defaults mirror Paystack Nigeria's published rates):

| Setting | Default |
| --- | --- |
| `WALLET_LOCAL_CARD_PERCENTAGE_FEE` / `_FLAT_FEE` / `_FEE_CAP` | `1.5` / `100` / `2000` |
| `WALLET_LOCAL_CARD_FEE_WAIVER_THRESHOLD` | `2500` (flat fee waived below this) |
| `WALLET_INTL_CARD_PERCENTAGE_FEE` / `_FLAT_FEE` / `_FEE_CAP` | `3.9` / `100` / `None` |
| `WALLET_DVA_PERCENTAGE_FEE` / `_FLAT_FEE` / `_FEE_CAP` | `1.0` / `0` / `300` |
| `WALLET_MOBILE_MONEY_PERCENTAGE_FEE` / `_FLAT_FEE` / `_FEE_CAP` | `1.95` / `0` / `None` |
| `WALLET_TRANSFER_FEE_TIERS` | ≤5,000 → 10; ≤50,000 → 25; above → 50 (tiers may also have a `percentage`) |
| `WALLET_INTERNAL_TRANSFER_PERCENTAGE_FEE` / `_FLAT_FEE` / `_FEE_CAP` | `0` / `0` / `None` |
| `WALLET_PAYMENT_PERCENTAGE_FEE` / `_FLAT_FEE` / `_FEE_CAP` | `0` / `0` / `None` |
| `WALLET_FEE_SPLIT_CUSTOMER_PERCENTAGE` / `_MERCHANT_PERCENTAGE` | `50` / `50` (must add up to 100) |
| `WALLET_ENABLE_EDUCATIONAL_PRICING` | `False` |
| `WALLET_EDUCATIONAL_CARD_PERCENTAGE_FEE` / `_FEE_CAP` | `0.7` / `1500` |

## Settlements

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_AUTO_SETTLEMENT` | `False` | Run threshold schedules as soon as money lands in a wallet |

## Notifications

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_NOTIFICATION_BACKENDS` | `[]` | e.g. `['wallet.notifications.backends.EmailNotificationBackend']` |
| `WALLET_EMAIL_SENDER` | `None` (→ `DEFAULT_FROM_EMAIL`) | |

## Checkout

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_DEFAULT_CALLBACK_URL` | `None` | Sent to Paystack when a deposit has no `callback_url` |
| `WALLET_CALLBACK_REDIRECT_URL` | `None` | The callback view redirects here with `?reference=&status=` (else renders a page) |
| `WALLET_PAYMENT_CHANNELS` | `None` | Restrict checkout channels, e.g. `card,bank_transfer` |
| `WALLET_RECONCILE_AFTER_MINUTES` | `10` | Age before pending transactions are re-checked with Paystack |
| `WALLET_RECONCILE_BATCH_SIZE` | `500` | Pending deposits and withdrawals checked per run (each) |

## Data retention

`manage.py prune_wallet_data` (or `wallet.tasks.prune_wallet_data_task`) deletes old
operational data. **Ledger data (transactions, settlements) is never pruned.**

| Setting | Default | Notes |
| --- | --- | --- |
| `WALLET_WEBHOOK_RETENTION_DAYS` | `90` | Processed webhook events and delivery attempts older than this are deleted. `None` keeps them. Unprocessed events are always kept |
| `WALLET_WEBHOOK_RETRY_WINDOW_HOURS` | `72` | Failed outbound deliveries older than this are not retried |

## REST API

| Setting | Default |
| --- | --- |
| `WALLET_API_PERMISSION_CLASSES` | `['rest_framework.permissions.IsAuthenticated']` |
| `WALLET_API_PAGE_SIZE` | `20` |
| `WALLET_API_MAX_PAGE_SIZE` | `100` (clients may pass `?page_size=`) |

Authentication is whatever you configure in `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']`
(session, token, JWT, …).

## Banks & exports

| Setting | Default |
| --- | --- |
| `WALLET_AUTO_SYNC_BANKS` | `False` |
| `WALLET_BANK_COUNTRY` | `nigeria` |
| `WALLET_EXPORT_PAGESIZE` | `A4` (or `letter`) |
| `WALLET_EXPORT_ORIENTATION` | `portrait` (or `landscape`) |

## Removed settings

| Setting | Why |
| --- | --- |
| `WALLET_USE_UUID` | Models always use UUIDs. A primary-key type that changes with a setting cannot ship working migrations |
| `WALLET_SEND_EMAIL_NOTIFICATIONS` | Replaced by `WALLET_NOTIFICATION_BACKENDS` |
| `WALLET_USER_MODEL` | The wallet always uses `AUTH_USER_MODEL` |

Reading a removed setting raises `ImproperlyConfigured` with this explanation.
