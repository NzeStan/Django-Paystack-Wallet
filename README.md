# Django Paystack Wallet

A pluggable, production-grade wallet for Django, backed by [Paystack](https://paystack.com).
Drop it into an e-commerce site, marketplace, fintech or any app that needs users to hold,
send and receive money — and switch off anything you don't need.

- **Fund wallets** with card, bank, USSD, QR, mobile money, bank transfer or a
  **dedicated virtual account** (a personal NUBAN per user)
- **Withdraw** to bank accounts (Paystack Transfers) with OTP support
- **Send money between wallets** by wallet ID, **tag**, **phone number** or **email**
- **Pay with wallet** at checkout, with optional **escrow** for marketplaces
- **Fees** that are fully configurable: who pays (customer / merchant / platform / split),
  Paystack-accurate defaults, database-driven pricing per wallet, or your own calculator
- **Refunds** back to the payer's card, staff **reversals**, **settlements** (scheduled payouts)
- **Transaction PIN**, daily limits, minimum balances, webhook signature + IP checks
- **Every Paystack API** wrapped in one client (`wallet.paystack.PaystackClient`)
- **Signals** for every money movement, **pluggable notifications**, optional **Celery**
- REST API (Django REST Framework), Django admin, management commands, `.env` configuration

## Why it's safe with money

| Rule | What it prevents |
| --- | --- |
| Every balance change locks the wallet row (`SELECT … FOR UPDATE`) and is recorded as a ledger entry with `balance_after` | Double spending under concurrent requests; unexplained balances |
| Withdrawals debit **before** calling Paystack and reverse automatically on failure | Spending the same money twice while a transfer is in flight |
| Only a Paystack **rejection** reverses a withdrawal; timeouts stay pending and are reconciled | Paying out twice when Paystack succeeded but the response was lost |
| Webhooks are signature-checked, stored, de-duplicated and processed idempotently | Double credits from Paystack retries or a webhook racing a manual verify |
| Wallets are credited from what Paystack **actually collected**, never from the client | Under-payment and tampered amounts |
| Signals fire only after the database commits | Sending "you've been paid" for a transaction that rolled back |
| `Idempotency-Key` support on every money-moving endpoint | Double charges when a mobile app retries after a timeout |
| Per-user rate limits on lookups, PINs, OTPs and payments | Phone-number enumeration, PIN/OTP guessing, abuse |
| Audit log of every refund, reversal, escrow decision and lock | "Who did this?" |

These are covered by 520+ tests, including race-condition tests against PostgreSQL, and
[a ledger benchmark](loadtest/README.md) that proves the books balance under load.

## Installation

```bash
pip install django-paystack-wallet            # core
pip install "django-paystack-wallet[celery]"  # + background tasks
pip install "django-paystack-wallet[export]"  # + Excel/PDF exports
```

```python
# settings.py
from pathlib import Path
from wallet.conf import load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent
load_env_file(BASE_DIR / '.env')          # optional: or use python-dotenv / django-environ

INSTALLED_APPS = [
    # ...
    'rest_framework',
    'djmoney',
    'wallet',
]
```

```python
# urls.py
urlpatterns = [
    # ...
    path('wallet/', include('wallet.urls')),
]
```

```bash
cp .env.example .env        # then set PAYSTACK_SECRET_KEY / PAYSTACK_PUBLIC_KEY
python manage.py migrate
python manage.py sync_banks
python manage.py check      # the package validates its own configuration
```

In the [Paystack dashboard](https://dashboard.paystack.com/#/settings/developers) set the
webhook URL to `https://your-domain.com/wallet/webhook/`.

That's it: every user gets a wallet automatically, and the API is live under `/wallet/api/`.

## Try it in 5 minutes

The [`demo/`](demo/README.md) folder is a small Django site built on the package: fund a
wallet through real Paystack test checkout, send money by phone number, withdraw to a
bank, save cards, buy from a mini marketplace with escrow, and watch webhooks arrive.

```bash
pip install -e ".[all]"
cd demo && cp .env.example .env      # add your Paystack TEST keys
python manage.py migrate && python manage.py seed_demo && python manage.py runserver
```

## A quick tour

```python
from wallet.services import WalletService

service = WalletService()
wallet = service.get_wallet(request.user)

# Fund it (redirect the user to checkout['authorization_url'])
checkout = service.initialize_deposit(wallet, 5000, callback_url='https://shop.com/paid')

# Send money — by phone number, tag, email or wallet id
service.set_phone_number(wallet, '0803 123 4567')
service.transfer(wallet, '08099998888', 1500, description='Lunch')
service.transfer(wallet, '@ada', 2000)

# Pay a seller, held in escrow until delivery
order_payment = service.pay(buyer_wallet, 25000, merchant_wallet=seller_wallet, escrow=True)
service.release_payment(order_payment)          # or service.cancel_payment(order_payment)

# Withdraw to a bank account
account = service.add_bank_account(wallet, bank_code='058', account_number='0123456789')
txn, transfer = service.withdraw_to_bank(wallet, 10000, account)
if txn.requires_otp:
    service.finalize_withdrawal(txn, otp='123456')

# Anything else Paystack offers
from wallet.paystack import get_paystack_client
paystack = get_paystack_client()
paystack.subscriptions.create(customer='CUS_xxx', plan='PLN_xxx')
```

React to money movement with signals:

```python
from django.dispatch import receiver
from wallet.signals import deposit_completed, transfer_completed

@receiver(deposit_completed)
def fulfil(sender, transaction, wallet, **kwargs):
    ...
```

## Use only what you need

Everything is switchable with a setting or environment variable:

```bash
WALLET_ENABLE_WITHDRAWALS=false
WALLET_ENABLE_INTERNAL_TRANSFERS=true
WALLET_ENABLE_PAYMENTS=true
WALLET_ENABLE_DEDICATED_ACCOUNTS=false
WALLET_ENABLE_SETTLEMENTS=false
WALLET_ENABLE_FEES=true
WALLET_REQUIRE_TRANSACTION_PIN=true
```

What is core and what is pluggable:

| Core (always there) | Pluggable (opt in / replace) |
| --- | --- |
| Ledger, wallets, transactions, locking | Notifications (`WALLET_NOTIFICATION_BACKENDS`) |
| Paystack client & webhook handling | Fee pricing (`WALLET_FEE_CALCULATOR`, DB configs) |
| Fee *mechanics* (who pays, how much moves) | Phone normalisation (`WALLET_PHONE_NUMBER_NORMALIZER`) |
| Signals | Background processing (Celery) |
| | REST API permissions (`WALLET_API_PERMISSION_CLASSES`), URLs, admin |
| | Webhook forwarding to other services, Excel/PDF export |

## Documentation

- [Installation](docs/installation.md)
- [Configuration & environment variables](docs/configuration.md)
- [Usage guide](docs/usage.md): deposits, transfers by phone, payments & escrow, withdrawals, fees, refunds, settlements
- [REST API reference](docs/api_reference.md)
- [Extending](docs/extending.md): signals, notifications, custom fees, your own endpoints, the Paystack client

## Load testing

`loadtest/benchmark_ledger.py` measures ledger throughput on your database and checks
the books balance afterwards; `loadtest/locustfile.py` load-tests your full HTTP stack.
See [loadtest/README.md](loadtest/README.md).

## Development

```bash
pip install -e ".[dev]"
pytest                                     # SQLite
pytest --ds=your_postgres_settings         # includes the race-condition tests
```

## License

MIT — see [LICENSE](LICENSE).
