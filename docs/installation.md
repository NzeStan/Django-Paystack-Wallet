# Installation

## Requirements

- Python 3.10+
- Django 4.2+
- Django REST Framework 3.14+
- A Paystack account (test keys are fine to start)
- PostgreSQL or MySQL in production (SQLite works for development, but it has no
  row-level locking, so concurrent requests are not isolated there)

## 1. Install

```bash
pip install django-paystack-wallet
```

Optional extras:

| Extra | Adds | Needed for |
| --- | --- | --- |
| `celery` | Celery | Background webhook processing, scheduled reconciliation/payouts |
| `export` | xlsxwriter, reportlab | Excel and PDF exports (CSV works without it) |
| `all` | both | |

```bash
pip install "django-paystack-wallet[celery,export]"
```

## 2. Settings

```python
from pathlib import Path
from wallet.conf import load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent
load_env_file(BASE_DIR / '.env')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    # ...
    'rest_framework',
    'djmoney',
    'wallet',
]

USE_TZ = True
```

`load_env_file` is a tiny, dependency-free `.env` reader. Variables that are already set
in the real environment always win, so production values are never replaced by a stray
file. If you already use `python-dotenv` or `django-environ`, keep using them: the wallet
reads plain environment variables.

## 3. Environment

```bash
cp .env.example .env
```

At minimum set:

```bash
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
```

Every other setting has a sensible default. See [configuration](configuration.md).
Check what is actually in effect with:

```bash
python manage.py wallet_settings
```

## 4. URLs

```python
from django.urls import include, path

urlpatterns = [
    path('wallet/', include('wallet.urls')),
]
```

This gives you:

| Path | Purpose |
| --- | --- |
| `/wallet/api/...` | REST API ([reference](api_reference.md)) |
| `/wallet/webhook/` | Paystack webhook receiver |
| `/wallet/callback/` | Where Paystack sends customers back after checkout |

The URLs are namespaced (`wallet:paystack-webhook`, `wallet:payment-callback`, …).
Prefer to expose only some endpoints? See [extending](extending.md#your-own-endpoints).

## 5. Database and banks

```bash
python manage.py migrate
python manage.py sync_banks                            # Nigerian banks
python manage.py sync_banks --country ghana --currency GHS
```

Or set `WALLET_AUTO_SYNC_BANKS=true` to sync automatically after the first `migrate`.

## 6. Paystack dashboard

In **Settings → API Keys & Webhooks**:

- **Webhook URL**: `https://your-domain.com/wallet/webhook/`
- **Callback URL** (optional): `https://your-domain.com/wallet/callback/`
  (or set `WALLET_DEFAULT_CALLBACK_URL`)

Webhooks are how deposits, transfers and refunds complete. Locally, expose your dev
server with a tunnel (ngrok, cloudflared) to receive them.

## 7. Scheduled jobs

Webhooks can be delayed or lost, so run the reconciliation safety net periodically.

**With cron / a scheduler:**

```bash
*/10 * * * *  python manage.py reconcile_transactions    # verify stale deposits & withdrawals
*/15 * * * *  python manage.py process_settlements        # scheduled payouts (if you use them)
*/15 * * * *  python manage.py retry_webhook_deliveries   # only if you forward webhooks
0 3 * * *     python manage.py prune_wallet_data          # keep webhook/idempotency tables small
```

**With Celery** (`WALLET_USE_CELERY=true`):

```python
CELERY_BEAT_SCHEDULE = {
    'wallet-reconcile': {'task': 'wallet.tasks.reconcile_transactions_task', 'schedule': 600},
    'wallet-settlements': {'task': 'wallet.tasks.process_due_settlements_task', 'schedule': 900},
    'wallet-webhook-retries': {'task': 'wallet.tasks.retry_failed_webhook_deliveries_task', 'schedule': 900},
    'wallet-expired-cards': {'task': 'wallet.tasks.check_expired_cards_task', 'schedule': 86400},
    'wallet-prune': {'task': 'wallet.tasks.prune_wallet_data_task', 'schedule': 86400},
}
```

With Celery on, webhooks are acknowledged immediately and processed on your workers.

## 8. Production essentials

- **PostgreSQL** (or MySQL/InnoDB). SQLite has no row locks.
- **A shared cache** (Redis/Memcached) as `CACHES['default']`, so rate limits work across
  servers.
- **Celery** for webhook processing at volume.
- Mobile/web clients send an **`Idempotency-Key`** header on money-moving requests.
- Route the **`wallet.audit`** logger to durable storage.

See [`loadtest/README.md`](../loadtest/README.md) for benchmarking your setup.

## 9. Verify

```bash
python manage.py check
```

The package registers system checks for missing or mismatched Paystack keys, live keys
with `DEBUG=True`, invalid fee bearers, bad dotted paths, Celery enabled but not
installed, and more.

## Upgrading from the pre-1.0 code

1.0 ships a fresh `0001_initial` migration. If you ran an earlier development
version against a database you want to keep, back it up, then either start from a
fresh database or fake the initial migration after aligning the schema by hand. See
the [changelog](../CHANGELOG.md) for everything that changed.
