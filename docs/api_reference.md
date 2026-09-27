# REST API reference

All endpoints live under the prefix you include the URLs at (examples use `/wallet/`).
Authentication is your Django REST Framework authentication (session, token, JWT, …);
permissions default to `IsAuthenticated` (`WALLET_API_PERMISSION_CLASSES`).

Users only ever see their own wallet, transactions, cards, bank accounts and settlements.
Amounts are decimal strings (`"1500.00"`) in the wallet's currency. Lists are paginated:

```json
{"count": 42, "next": "…?page=2", "previous": null, "results": [ … ]}
```

(`?page=2&page_size=50`, up to `WALLET_API_MAX_PAGE_SIZE`.)

## Errors

Business errors:

```json
{"detail": "Recipient wallet not found", "code": "recipient_not_found"}
```

Validation errors (standard DRF):

```json
{"amount": ["Ensure this value is greater than or equal to 0.01."]}
```

| HTTP | Common `code`s |
| --- | --- |
| 400 | `insufficient_funds`, `invalid_amount`, `limit_exceeded`, `minimum_balance`, `recipient_error`, `bank_account_error`, `card_error`, `currency_mismatch`, `invalid_phone_number`, `pin_required`, `pin_not_set`, `settlement_error` |
| 403 | `wallet_locked`, `wallet_inactive`, `feature_disabled`, `invalid_pin`, `pin_locked` |
| 404 | `not_found`, `recipient_not_found`, `wallet_not_found`, `bank_account_not_found`, `card_not_found` |
| 409 | `duplicate_reference`, `invalid_transaction_state`, `idempotency_in_progress` |
| 422 | `idempotency_key_reused` |
| 429 | rate limited (`Retry-After` header) |
| 400 | `paystack_rejected`: Paystack refused the request (e.g. wrong OTP, invalid account); `detail` is Paystack's message |
| 502 | `paystack_error`: Paystack was unreachable or failed; the outcome may be unknown, so check the transaction before retrying |

When `WALLET_REQUIRE_TRANSACTION_PIN` is on, send `"pin": "1234"` with withdraw, transfer,
pay, charge-card and settlement requests.

## Idempotency keys

Send `Idempotency-Key: <a new UUID per operation>` with every money-moving POST
(deposit, charge-card, withdraw, finalize-withdrawal, transfer, pay, card charge,
settlement create/finalize, and the staff refund/reverse/release/cancel actions).
If the network drops and the app retries with the **same key and body**, the API returns
the original response (with header `Idempotent-Replayed: true`) instead of moving money
again. Keys are per user and remembered for `WALLET_IDEMPOTENCY_TTL_HOURS`.

| Situation | Response |
| --- | --- |
| Same key, same body, first request finished | Original status and body, `Idempotent-Replayed: true` |
| Same key, first request still running | `409 idempotency_in_progress` |
| Same key, different body | `422 idempotency_key_reused` |
| No key while `WALLET_REQUIRE_IDEMPOTENCY_KEY` is on | `400 idempotency_key_required` |
| First attempt hit a server error (5xx) | Not stored; retrying with the same key is safe |

## Rate limits

Sensitive endpoints are rate limited per user (`WALLET_THROTTLE_RATES`). Over the limit
you get `429` with a `Retry-After` header.

---

## Wallets

`{id}` is the wallet UUID or `me`.

### `GET /wallet/api/wallets/me/`

```json
{
  "id": "870da5a6-3072-4f4d-8bff-92593f0762a9",
  "tag": "ada",
  "phone_number": "+2348031234567",
  "balance": "43475.00",
  "currency": "NGN",
  "is_active": true,
  "is_locked": false,
  "is_operational": true,
  "has_pin": false,
  "dedicated_account": {"account_number": "9930000001", "account_name": "ADA OBI", "bank_name": "Wema Bank", "active": true},
  "last_transaction_date": "2026-09-27T04:14:29.535732+01:00",
  "created_at": "2026-09-27T04:14:29.422350+01:00",
  "updated_at": "2026-09-27T04:14:29.422366+01:00",
  "daily_limit": null,
  "daily_spent": "10025.00",
  "customer_identified": false
}
```

### `PATCH /wallet/api/wallets/me/`

```json
{"tag": "ada.pay", "phone_number": "0803 123 4567"}
```

Phone numbers are normalised (`+2348031234567`) and must be unique; tags are 3-30
characters (letters, digits, `.`, `-`, `_`) and unique.

### `GET /wallet/api/wallets/me/balance/`

```json
{"balance": "43475.00", "currency": "NGN", "is_operational": true, "updated_at": "2026-09-27T03:14:29Z"}
```

### `GET /wallet/api/wallets/me/transactions/`

Filters: `type`, `status`, `direction` (`credit`/`debit`), `search` (reference or
description), `start_date`, `end_date` (`YYYY-MM-DD` covers the whole day, or ISO datetime).

### `GET /wallet/api/wallets/me/statement/`

Posted entries (with `balance_after`) oldest first. Takes `start_date` and `end_date`.

### `POST /wallet/api/wallets/me/deposit/`

Start a Paystack checkout.

| Field | Required | Notes |
| --- | --- | --- |
| `amount` | ✔ | Amount to credit |
| `email` | | Defaults to the user's email |
| `callback_url` | | Where Paystack returns the customer (default `WALLET_DEFAULT_CALLBACK_URL`) |
| `channels` | | e.g. `["card", "bank_transfer", "ussd"]` |
| `reference` | | Your own unique reference |
| `description`, `metadata` | | `metadata` is echoed in webhooks |
| `fee_bearer` | | Only if `WALLET_ALLOW_FEE_BEARER_OVERRIDE` (or staff) |

`201`:

```json
{
  "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
  "access_code": "0peioxfhpn",
  "reference": "DEP-1790478869-OMCF7MOPCN",
  "transaction_id": "353c1fa2-ffda-43ed-9171-64603e4d29d0",
  "amount": "5000.00",
  "charge_amount": "5000.00",
  "currency": "NGN",
  "public_key": "pk_test_…",
  "fee_breakdown": {"fee_amount": "0.00", "bearer": "platform", "customer_pays": "5000.00", "merchant_receives": "5000.00", "…": "…"}
}
```

Redirect to `authorization_url`, or open Paystack InlineJS with `access_code` and
`public_key`. The wallet is credited by the webhook, or when you call:

### `POST /wallet/api/wallets/me/verify-deposit/`

```json
{"reference": "DEP-1790478869-OMCF7MOPCN"}
```

Returns the transaction. Safe to call repeatedly: a deposit is credited only once.

### `POST /wallet/api/wallets/me/charge-card/`

Top up from a saved card: `{"amount": "3000", "card_id": "…"}` (default card if
omitted). `200` if charged now, `202` if the bank needs another step (the webhook
completes it).

### `POST /wallet/api/wallets/me/withdraw/`

| Field | Required | Notes |
| --- | --- | --- |
| `amount` | ✔ | Amount the bank account should receive |
| `bank_account_id` | | Default bank account if omitted |
| `description`, `reference`, `metadata`, `fee_bearer`, `pin` | | `reference`: 16-50 lowercase letters, digits, `-`, `_` |

Response (`200` success, `202` processing / OTP needed, `400` failed):

```json
{
  "status": "pending_otp",
  "message": "Enter the OTP to complete the withdrawal",
  "transaction": {
    "id": "4b1a19b2-ba73-46ab-94bf-c16eb034d58a",
    "reference": "wdr-1790478869-p4w5ehseav",
    "transaction_type": "withdrawal",
    "direction": "debit",
    "status": "pending",
    "amount": "10000.00",
    "fees": "25.00",
    "total_amount": "10025.00",
    "balance_after": "43475.00",
    "bank_account": {"id": "…", "bank_name": "Test Bank", "account_name": "ADA OBI", "account_number": "******6789"},
    "requires_otp": true,
    "paystack_transfer_code": "TRF_1ptvuv321ahaa7q",
    "…": "…"
  }
}
```

`status` is one of `success`, `pending_otp`, `processing`, `failed`.

### `POST /wallet/api/wallets/me/finalize-withdrawal/`

```json
{"otp": "123456", "transaction_id": "4b1a19b2-…"}
```

Identify the withdrawal with `transaction_id`, `reference` or `transfer_code`. A wrong
OTP returns `400 paystack_rejected` with Paystack's message; the withdrawal stays pending.

### `POST /wallet/api/wallets/me/resend-otp/`

Same identifiers as above.

### `GET /wallet/api/wallets/lookup/?recipient=08031234567`

Confirm a recipient before sending (`recipient_type` optional: `id`, `tag`,
`phone_number`, `email`):

```json
{"wallet_id": "5fba474c-…", "tag": "bola", "name": "Bola A.", "phone_number": "+234809****888", "can_receive": true}
```

### `POST /wallet/api/wallets/me/transfer/`

| Field | Required | Notes |
| --- | --- | --- |
| `recipient` | ✔* | Wallet ID, tag, phone number (any format) or email |
| `recipient_type` | | Force the lookup: `id`, `tag`, `phone_number`, `email` |
| `phone_number` | ✔* | Shortcut for `recipient` + `recipient_type=phone_number` |
| `destination_wallet_id` | ✔* | Shortcut for `recipient` + `recipient_type=id` |
| `amount` | ✔ | |
| `description`, `reference`, `metadata`, `fee_bearer`, `pin` | | |

\* one of them. `201` returns the sender's (debit) transaction:

```json
{
  "id": "22d2a663-0eb9-46e3-be53-968818b29f9e",
  "reference": "TRF-1790478869-DZC5JONN9U",
  "transaction_type": "transfer",
  "direction": "debit",
  "status": "success",
  "amount": "1500.00",
  "fees": "0.00",
  "total_amount": "1500.00",
  "balance_after": "53500.00",
  "currency": "NGN",
  "counterparty": {"wallet_id": "5fba474c-…", "tag": "bola"},
  "related_transaction": "f2ed0823-…",
  "description": "Lunch",
  "…": "…"
}
```

### `POST /wallet/api/wallets/me/pay/`

```json
{"amount": "15000", "merchant": "seller-tag", "escrow": true, "description": "Order #1001", "metadata": {"order_id": 1001}}
```

`merchant` is optional (omit it and the platform keeps the payment). With `escrow`, the
payment stays `pending` until the buyer or staff releases it, or staff cancels it (see
transactions). Buyers cannot cancel an escrow themselves.

### `POST /wallet/api/wallets/me/set-pin/`

```json
{"pin": "4826", "confirm_pin": "4826", "current_pin": "…only when changing…"}
```

Obvious PINs (`1111`, `1234`, …) are rejected.

### `GET | POST /wallet/api/wallets/me/dedicated-account/`

`GET` returns the account (`404` if none). `POST` (`{"preferred_bank": "wema-bank"}`
optional) creates it:

```json
{"account_number": "9930000002", "account_name": "ADA OBI", "bank_name": "Wema Bank", "bank_slug": "wema-bank", "active": true}
```

### `POST /wallet/api/wallets/me/requery-dedicated-account/`

Asks Paystack to re-check for transfers into the account (`{"date": "2026-09-27"}`
optional). New money arrives by webhook.

### `POST /wallet/api/wallets/me/validate-customer/`

Paystack identity validation, needed before a DVA for most Nigerian businesses. Returns
`202`; the result arrives by webhook.

```json
{"first_name": "Ada", "last_name": "Obi", "identification_type": "bank_account", "bvn": "22222222222", "bank_code": "058", "account_number": "0123456789"}
```

### `POST /wallet/api/wallets/fee-quote/`

```json
{"amount": "10000", "transaction_type": "withdrawal", "payment_channel": "local_card"}
```

```json
{"original_amount": "10000.00", "fee_amount": "25.00", "bearer": "customer", "customer_pays": "10025.00", "merchant_receives": "10000.00", "source": "settings", "…": "…"}
```

`transaction_type`: `deposit`, `withdrawal`, `transfer`, `payment`. `payment_channel`
(deposits): `local_card`, `intl_card`, `dva`, `bank_transfer`, `ussd`, `qr`,
`mobile_money`, `bank`.

---

## Transactions

| Method & path | Who | Description |
| --- | --- | --- |
| `GET /wallet/api/transactions/` | owner | Filters: `type`, `status`, `direction`, `payment_method`, `search`, `start_date`, `end_date` |
| `GET /wallet/api/transactions/{id}/` | owner | Includes `metadata`, Paystack references |
| `POST /wallet/api/transactions/verify/` | owner | `{"reference": "…"}`: re-check a deposit with Paystack |
| `POST /wallet/api/transactions/{id}/cancel/` | owner / staff | Owner: an unpaid deposit. Staff: an escrowed payment (refunds the buyer). `{"reason": "…"}` |
| `POST /wallet/api/transactions/{id}/release/` | buyer / staff | Release an escrowed payment to the seller (e.g. buyer confirms delivery) |
| `POST /wallet/api/transactions/{id}/refund/` | staff | Refund a deposit to the payer's card/bank (`{"amount": "…", "reason": "…"}`) |
| `POST /wallet/api/transactions/{id}/reverse/` | staff | Reverse a transfer or payment |
| `GET /wallet/api/transactions/statistics/` | owner | Counts, credits, debits, fees |
| `GET /wallet/api/transactions/summary/` | owner | Grouped by type and status |
| `GET /wallet/api/transactions/export/?export_format=csv` | owner | `csv`, `xlsx`, `pdf` (xlsx/pdf need the `export` extra); same filters as the list |

## Cards

| Method & path | Description |
| --- | --- |
| `GET /wallet/api/cards/` | Active saved cards (`?include_inactive=true`) |
| `GET /wallet/api/cards/{id}/` | |
| `DELETE /wallet/api/cards/{id}/` | Remove, and revoke the authorization on Paystack |
| `POST /wallet/api/cards/{id}/set-default/` | |
| `POST /wallet/api/cards/{id}/charge/` | `{"amount": "3000"}`: top up the wallet from this card |

Cards are added automatically when the user pays with a reusable card.

## Banks & bank accounts

| Method & path | Description |
| --- | --- |
| `GET /wallet/api/banks/` | `?country=`, `?currency=`, `?search=` |
| `POST /wallet/api/bank-accounts/resolve/` | `{"bank_code": "058", "account_number": "0123456789"}` returns `{"account_name": "ADA OBI", …}` |
| `GET /wallet/api/bank-accounts/` | |
| `POST /wallet/api/bank-accounts/` | `{"bank_code", "account_number", "account_type"?, "currency"?, "set_default"?}`; the name is verified with Paystack |
| `GET /wallet/api/bank-accounts/{id}/` | |
| `DELETE /wallet/api/bank-accounts/{id}/` | |
| `POST /wallet/api/bank-accounts/{id}/set-default/` | |

## Settlements

| Method & path | Description |
| --- | --- |
| `GET /wallet/api/settlements/` | `?status=` |
| `POST /wallet/api/settlements/` | `{"amount", "bank_account_id"?, "reason"?, "pin"?}` |
| `GET /wallet/api/settlements/{id}/` | |
| `POST /wallet/api/settlements/{id}/finalize/` | `{"otp": "…"}` |
| `POST /wallet/api/settlements/{id}/verify/` | Re-check with Paystack |
| `POST /wallet/api/settlements/{id}/retry/` | Failed settlements only |
| `GET /wallet/api/settlements/statistics/` | |
| `GET, POST /wallet/api/settlement-schedules/` | `{"bank_account_id", "schedule_type": "daily\|weekly\|monthly\|threshold", "day_of_week"?, "day_of_month"?, "time_of_day"?, "amount_threshold"?, "minimum_amount"?, "maximum_amount"?}` |
| `GET, PATCH, DELETE /wallet/api/settlement-schedules/{id}/` | |
| `POST /wallet/api/settlement-schedules/{id}/activate/` · `/deactivate/` | |

## Webhooks

| Method & path | Who | Description |
| --- | --- | --- |
| `POST /wallet/webhook/` | Paystack | `200` for authentic events (including duplicates), `401` bad signature/IP, `400` malformed |
| `GET /wallet/api/webhook-events/` | staff | `?event_type=`, `?processed=true\|false` |
| `POST /wallet/api/webhook-events/{id}/reprocess/` | staff | Replay an event |
| `CRUD /wallet/api/webhook-endpoints/` | staff | Endpoints that receive signed copies (`WALLET_ENABLE_WEBHOOK_FORWARDING`) |
| `POST /wallet/api/webhook-endpoints/{id}/test/` | staff | Send the latest event |
| `GET /wallet/api/webhook-deliveries/` · `POST …/{id}/retry/` | staff | Delivery log and retries |

Forwarded deliveries carry `X-Wallet-Event`, `X-Wallet-Event-Id`,
`X-Wallet-Delivery-Attempt` and, when the endpoint has a secret,
`X-Wallet-Signature` = HMAC-SHA512 of the raw body keyed by the secret.

## Checkout callback

`GET /wallet/callback/?reference=…` verifies the payment with Paystack, then redirects
to `WALLET_CALLBACK_REDIRECT_URL?reference=…&status=…` or renders
`wallet/payment_callback.html` (override the template to match your site).
