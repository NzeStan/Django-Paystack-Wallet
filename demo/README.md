# Demo project: test the wallet against real Paystack

A small Django site built on `django-paystack-wallet`. It uses the package code from this
repository directly, so any change you make to `wallet/` shows up on the next reload.

What you can do in it:

| Page | What it exercises |
| --- | --- |
| Dashboard | Live balance, **Paystack checkout** (cards, bank transfer, USSD…), fee quotes, tag & phone, virtual account, PIN |
| Send | Recipient preview, **transfers by phone / @tag / email**, idempotent retries |
| Withdraw | Bank list, account-name verification, **withdrawals to bank**, OTP flow |
| Cards | Saved cards (from checkout), charging a saved card |
| History | Filters, pagination, CSV export, the ledger statement |
| Shop / Orders | A mini marketplace: **wallet payments with escrow**, confirm delivery, seller refunds, 5% commission |
| Developer (staff) | Webhooks received, replay, reconcile with Paystack, sync banks, resolved settings |
| `/admin/` | Everything, with service-backed actions (refunds, reversals, locks…) |
| `/wallet/api/` | The browsable REST API |

## 1. Set up (5 minutes)

From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -e ".[all]"

cd demo
cp .env.example .env          # Windows: copy .env.example .env
```

Open `demo/.env` and paste your **test** keys from the Paystack dashboard (switch it to
**Test Mode** → Settings → API Keys & Webhooks):

```
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
```

Then:

```bash
python manage.py migrate
python manage.py seed_demo     # users, starting balances, products, and Paystack's bank list
python manage.py runserver
```

Open http://127.0.0.1:8000 and log in:

| User | Password | Notes |
| --- | --- | --- |
| `ada` | `demo12345` | ₦50,000 starting balance, phone 08031111111 |
| `bola` | `demo12345` | ₦50,000 starting balance, phone 08032222222 |
| `seller` | `demo12345` | sells the shop products |
| `admin` | `admin12345` | staff: Developer page and `/admin/` |

The starting balances are direct ledger credits, so you can test transfers and the shop
without paying first. Real Paystack money flows start at step 3.

## 2. Receive webhooks on your laptop (recommended)

Paystack confirms payments, transfers and refunds by calling your webhook URL, and it
can't reach `localhost`. Expose the demo with a tunnel:

```bash
# Option A - Cloudflare (no account needed)
cloudflared tunnel --url http://127.0.0.1:8000

# Option B - ngrok
ngrok http 8000
```

Then:

1. **Open the demo through the tunnel URL** (e.g. `https://random-words.trycloudflare.com`),
   not `127.0.0.1`, so Paystack redirects back to an address it can reach.
2. Log in as `admin`, open **Developer**, and copy the **Webhook URL** shown there.
3. Paste it into Paystack → Settings → API Keys & Webhooks → **Test Webhook URL**.

Every webhook then shows up on the Developer page, and balances update live on the
dashboard.

**No tunnel?** Deposits still work: after checkout, Paystack sends you back to
`/wallet/callback/`, which verifies the payment with Paystack's API. For withdrawals and
refunds, press **Reconcile** on the Developer page (or run
`python manage.py reconcile_transactions --older-than 0`).

## 3. Things to try

**Funding**
- [ ] Dashboard → Fund ₦5,000 → pay with the test card `4084 0840 8408 4081`, any future
      expiry, CVV `408`, PIN `0000`, OTP `123456` → back on the dashboard, balance +₦5,000
      (fees are on and paid by the customer, so checkout charges a little more).
- [ ] Try **Bank Transfer** or **USSD** on the checkout page.
- [ ] Cards → your test card was saved → top up ₦1,000 from it (no checkout page).
- [ ] Dashboard → **Get my account number** (virtual account). Some Paystack businesses
      must validate the customer first; the error message says so.

**Sending money**
- [ ] Send → `0803 222 2222` → **Check** shows "Bola A." → send ₦1,500.
- [ ] Press **Simulate network retry**: the response says "(replayed)" and Bola is only
      credited once.
- [ ] Send to `@bola`, to `bola@example.com`, to yourself (refused), more than you have (refused).

**Withdrawing**
- [ ] Withdraw → choose your bank → your real account number → **Verify name** → save.
      Test-mode transfers never move real money.
- [ ] Withdraw ₦2,000. If your Paystack account has transfer OTP on, enter the OTP; a
      wrong OTP is rejected and you can retry.
- [ ] Watch the withdrawal turn **Success** when the `transfer.success` webhook arrives
      (or press Reconcile).

**Marketplace**
- [ ] As `ada`: Shop → buy "Wireless earbuds" → Orders shows *held in escrow*; Ada is
      debited, the seller isn't paid yet.
- [ ] **Confirm delivery** → the seller gets ₦14,250 (₦15,000 minus the 5% commission).
- [ ] Buy again, log in as `seller` → Orders → **refund buyer** → Ada gets it all back.

**Security & configuration**: edit `demo/.env`, then restart `runserver`:
- [ ] `WALLET_REQUIRE_TRANSACTION_PIN=true`: sending, withdrawing and shopping ask for the PIN;
      5 wrong PINs lock it for 30 minutes.
- [ ] `WALLET_MAXIMUM_DAILY_TRANSACTION=5000`: the second big transfer of the day is refused.
- [ ] `WALLET_THROTTLE_RATES={"lookup": "3/min", "pin": "5/min", "money": "5/min", "otp": "5/min", "resolve": "10/min"}`:
      hammer **Check** on the Send page to see the rate limit (HTTP 429).
- [ ] `WALLET_ENABLE_WITHDRAWALS=false`: the withdrawal API answers 403.
- [ ] `WALLET_ENABLE_FEES=false`: no fees anywhere.

**Staff**
- [ ] `/admin/` → Transactions → select Ada's deposit → **Refund deposit to card**, then
      watch the `refund.processed` webhook arrive.
- [ ] `/admin/` → Transactions → reverse a transfer. The server terminal shows the audit
      log line with who did it.

The terminal running `runserver` prints what the wallet does: webhooks, notification
emails (console email backend), audit events and signals.

## 4. Reset

```bash
# delete demo/db.sqlite3, then
python manage.py migrate && python manage.py seed_demo
```

## 5. How the demo uses the package (read the code)

- `demo_project/settings.py`: the full integration: `load_env_file`, `INSTALLED_APPS`, DRF auth.
- `demo_project/urls.py`: one line, `path('wallet/', include('wallet.urls'))`.
- `shop/views.py`: calling the **service layer** from your own views (`WalletService().pay(...)`,
  `release_payment`, `cancel_transaction`).
- `shop/receivers.py`: reacting to **signals** (`payment_released`, `payment_cancelled`,
  `deposit_completed`).
- `shop/static/shop/app.js`: calling the **REST API** from a browser (CSRF + `Idempotency-Key`).
- `shop/tests.py`: `python manage.py test shop`.
