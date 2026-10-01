# Usage guide

Everything is available from one service object:

```python
from wallet.services import WalletService

service = WalletService()
wallet = service.get_wallet(user)      # created on first use (and automatically for new users)
```

Service methods raise subclasses of `wallet.exceptions.WalletError`. Each carries a
`message`, a machine-readable `code` and an `http_status`, so you can show them to users
directly.

```python
from wallet.exceptions import WalletError

try:
    service.transfer(wallet, '08031234567', 5000)
except WalletError as exc:
    return JsonResponse(exc.as_dict(), status=exc.http_status)
```

---

## The ledger

Every balance change is a `Transaction` row on the wallet it affects:

| Field | Meaning |
| --- | --- |
| `transaction_type` | `deposit`, `withdrawal`, `transfer`, `payment`, `refund`, `reversal`, `fee`, `commission` |
| `direction` | `credit` or `debit` on **this** wallet |
| `status` | `pending`, `processing`, `success`, `failed`, `cancelled`, `reversed` |
| `amount` | Face value of the operation |
| `fees` | Fee attached to the operation |
| `total_amount` | What actually moved on this wallet's balance |
| `balance_after` | Balance right after the posting (set once money moved) |
| `ledger_sequence` | 1, 2, 3, … per wallet: the exact order of postings, even when timestamps tie |
| `counterparty_wallet` | The other wallet in a transfer/payment |
| `related_transaction` | The other leg, or the original of a refund/reversal |

A wallet-to-wallet transfer creates **two** rows (sender debit + recipient credit), so
every wallet has a complete statement:

```python
service.get_statement(wallet, start_date, end_date)          # posted entries in ledger_sequence order
service.get_transaction_history(wallet, transaction_type='transfer', status='success')
```

Need to adjust a balance by hand (bonus, cash-back, correction)? Use the ledger, never
`wallet.balance = …`:

```python
service.credit_wallet(wallet, 500, description='Referral bonus', transaction_type='commission')
service.debit_wallet(wallet, 100, description='Card maintenance')
```

---

## Deposits

### Paystack checkout (card, bank, USSD, QR, mobile money, bank transfer)

```python
checkout = service.initialize_deposit(
    wallet, 5000,
    callback_url='https://shop.com/wallet/funded',   # optional (WALLET_DEFAULT_CALLBACK_URL)
    channels=['card', 'bank_transfer'],               # optional
    metadata={'order_id': 42},                        # returned in webhooks
)
checkout['authorization_url']   # redirect the customer here, or
checkout['access_code']         # use with Paystack InlineJS / Popup on your page
checkout['reference']
checkout['fee_breakdown']
```

A `pending` deposit is created. When the customer pays, Paystack's `charge.success`
webhook credits the wallet **exactly once**, based on the amount Paystack actually
collected and the channel actually used (a foreign card is priced as international).

If the customer comes back before the webhook, verify on demand; it's safe to call
repeatedly:

```python
txn = service.verify_deposit(reference)
```

The built-in `/wallet/callback/` view does this for you and then renders a result page,
or redirects to `WALLET_CALLBACK_REDIRECT_URL?reference=…&status=…`.

### Saved cards

Reusable cards are saved automatically after a card payment (the same physical card is
never duplicated). Charge them later without the checkout page:

```python
card = wallet.cards.filter(is_active=True).first()
txn = service.charge_card(card, 3000)
txn.status   # 'success', or 'pending' if the bank needs another step (the webhook finishes it)

service.remove_card(card)   # also revokes the authorization on Paystack
```

### Dedicated virtual account (bank transfer to a personal account number)

```python
service.create_dedicated_account(wallet, preferred_bank='wema-bank')
wallet.dedicated_account_number, wallet.dedicated_account_bank
```

Transfers into that account arrive as `charge.success` webhooks and are credited
automatically (matched by Paystack customer code or account number). DVA fees default to
being deducted from the credited amount (`WALLET_DVA_FEE_BEARER`).

Most Nigerian businesses must validate the customer's identity first:

```python
service.validate_customer(wallet, first_name='Ada', last_name='Obi',
                          bvn='22222222222', bank_code='058', account_number='0123456789')
# -> customeridentification.success webhook; with WALLET_AUTO_CREATE_DEDICATED_ACCOUNT the DVA follows
```

Or do it in one step and let the webhooks report back:

```python
service.assign_dedicated_account(wallet, phone='+2348031234567', preferred_bank='wema-bank',
                                 bvn='22222222222', account_number='0123456789', bank_code='058')
```

Other operations: `requery_dedicated_account`, `deactivate_dedicated_account`,
`dedicated_account_providers`, `get_dedicated_account`.

---

## Transfers between wallets

Recipients can be addressed by **wallet ID, tag, phone number or email**:

```python
service.transfer(sender, '08031234567', 2500)                    # phone, any format
service.transfer(sender, '+234 803 123 4567', 2500)
service.transfer(sender, '@ada', 2500)                            # tag
service.transfer(sender, 'ada@example.com', 2500)                 # email
service.transfer(sender, recipient_wallet, 2500)                  # a Wallet
service.transfer(sender, '0803...', 2500, lookup='phone_number')  # force the lookup type
```

Without `lookup`, the identifier is detected: a UUID is an ID, `@name` is a tag,
`x@y.z` is an email, and digits are tried as a phone number, then as a tag.

Give wallets a phone number or tag:

```python
service.set_phone_number(wallet, '0803 123 4567')   # stored as +2348031234567, unique
service.set_tag(wallet, 'ada.pay')                   # unique, case-insensitive
```

or copy it from your user model automatically with `WALLET_USER_PHONE_FIELD = 'phone'`.

Show the sender who they are paying before they confirm:

```python
recipient = service.resolve_recipient('08031234567')
service.describe_recipient(recipient)
# {'wallet_id': '…', 'tag': 'ada', 'name': 'Ada O.', 'phone_number': '+234803****567', 'can_receive': True}
```

Restrict how people may be found with
`WALLET_TRANSFER_RECIPIENT_LOOKUP_FIELDS = ['tag', 'phone_number']`.

---

## Paying with the wallet (e-commerce & marketplaces)

```python
# Your own shop: the platform keeps the money
service.pay(buyer_wallet, 15000, description='Order #1001', metadata={'order_id': 1001})

# Marketplace: a seller is credited (optionally minus your commission)
service.pay(buyer_wallet, 15000, merchant_wallet=seller_wallet)

# Escrow: the buyer is debited now, the seller is credited on release
payment = service.pay(buyer_wallet, 15000, merchant_wallet=seller_wallet, escrow=True)
service.release_payment(payment)                 # e.g. when delivery is confirmed
service.cancel_payment(payment, 'out of stock')  # or refund the buyer in full
```

Charge a marketplace commission with fees:

```python
WALLET_ENABLE_FEES = True
WALLET_ENABLE_PAYMENT_FEES = True
WALLET_PAYMENT_PERCENTAGE_FEE = 5          # 5% commission
WALLET_PAYMENT_FEE_BEARER = 'merchant'     # taken from what the seller receives
```

---

## Withdrawals to bank

```python
account = service.add_bank_account(wallet, bank_code='058', account_number='0123456789')
# Paystack verifies the account; the verified name is stored (never the user's input)

txn, transfer = service.withdraw_to_bank(wallet, 10000, account, reason='Savings')
```

The wallet is debited immediately and the transaction stays `pending` until Paystack
confirms:

| Outcome | What happens |
| --- | --- |
| `transfer.success` webhook | Transaction → `success` |
| `transfer.failed` webhook or Paystack rejects the request | Money returned, transaction → `failed` |
| `transfer.reversed` webhook (even after success) | Money returned, transaction → `reversed` |
| Timeout / Paystack 5xx | Stays `pending`; `reconcile_transactions` verifies it later |

If your Paystack account requires OTP for transfers:

```python
if txn.requires_otp:
    service.finalize_withdrawal(txn, otp='123456')   # a wrong OTP raises; the user can retry
    service.resend_withdrawal_otp(txn)
    service.cancel_otp_withdrawal(txn)                # gives the money back
```

---

## Fees

### Who pays

| Bearer | Deposit | Withdrawal | Transfer / payment |
| --- | --- | --- | --- |
| `customer` | Customer is charged amount + fee; wallet gets the amount | Wallet is debited amount + fee | Sender pays amount + fee |
| `merchant` | Customer pays the amount; wallet gets amount − fee | Wallet is debited the amount; bank gets amount − fee | Recipient gets amount − fee |
| `platform` | Nobody pays; the fee is recorded as your cost | same | same |
| `split` | Shared by `WALLET_FEE_SPLIT_*` percentages | same | same |

Quote a fee before doing anything:

```python
from wallet.services import calculate_fee

quote = calculate_fee(10000, 'withdrawal', wallet=wallet)
quote.fee_amount, quote.customer_pays, quote.merchant_receives, quote.to_dict()
```

or `POST /wallet/api/wallets/fee-quote/`.

### Where prices come from

1. **Your calculator**, if `WALLET_FEE_CALCULATOR` points to one ([extending](extending.md#custom-fee-pricing))
2. **Database configurations** (`WALLET_USE_DATABASE_FEE_CONFIG=true`), edited in the admin:
   per wallet or global, per channel, percentage / flat / hybrid / **tiered**, minimum,
   cap, waiver threshold, bearer, priority and validity dates. Most specific wins:
   wallet+channel → wallet → global+channel → global.
3. **Settings** (defaults mirror Paystack Nigeria's rates)

Every fee is audited in `FeeHistory`.

---

## Refunds and reversals

```python
from wallet.services import TransactionService

ts = TransactionService()

# Send (part of) a deposit back to the card/bank that paid it
refund = ts.refund_deposit(deposit_txn, amount=2000, reason='Returned item')
# The wallet is debited now; refund.processed completes it; refund.failed puts the money back.

# Undo a transfer or payment (e.g. sent to the wrong person) - staff operation
ts.reverse_transaction(transfer_txn, reason='Sent by mistake')

# Cancel an unpaid deposit or an escrowed payment
ts.cancel_transaction(txn)
```

---

## Settlements (payouts)

A settlement is a withdrawal with payout bookkeeping, handy for paying merchants on a
schedule.

```python
from wallet.services import SettlementService

ss = SettlementService()
ss.create_settlement(wallet, bank_account, 50000, reason='Weekly payout')

ss.create_settlement_schedule(wallet, bank_account, 'weekly', day_of_week=4)   # Fridays
ss.create_settlement_schedule(wallet, bank_account, 'monthly', day_of_month=31) # last day of each month
ss.create_settlement_schedule(wallet, bank_account, 'threshold', amount_threshold=100000)
```

Time-based schedules run with `manage.py process_settlements` (or the Celery beat task).
Threshold schedules pay out everything above the threshold as soon as money arrives, when
`WALLET_AUTO_SETTLEMENT=true`. Schedules respect `WALLET_MINIMUM_BALANCE` and their own
minimum and maximum amounts.

---

## Security features

```python
wallet.set_pin('4826')          # hashed; weak PINs are rejected by the API
wallet.verify_pin('4826')       # counts failures, locks after WALLET_PIN_MAX_ATTEMPTS

service.lock_wallet_account(wallet, 'Suspicious activity')   # blocks spending; incoming deposits still land
service.unlock_wallet_account(wallet)

wallet.daily_limit = 50000      # per-wallet override of WALLET_MAXIMUM_DAILY_TRANSACTION
wallet.save()
```

---

## Webhooks

Point Paystack at `/wallet/webhook/`. Every event is signature-checked, stored
(`WebhookEvent`), de-duplicated and processed:

| Event | Built-in handling |
| --- | --- |
| `charge.success` | Completes deposits, credits DVA transfers, saves cards |
| `transfer.success` / `transfer.failed` / `transfer.reversed` | Completes or reverses withdrawals and settlements |
| `refund.pending` / `processing` / `processed` / `failed` | Tracks refunds, restores money on failure |
| `dedicatedaccount.assign.success` / `failed` | Stores the account number |
| `customeridentification.success` / `failed` | Marks the customer identified (and creates the DVA if configured) |
| `charge.dispute.*` | `dispute_event` signal |
| everything else (subscriptions, invoices, payment requests, …) | `paystack_webhook_received` signal |

A failed handler never returns an error to Paystack. The event is kept with its error
and can be replayed from the admin, from `POST /wallet/api/webhook-events/{id}/reprocess/`,
or with `WebhookService().reprocess_webhook_event(id)`.

---

## Everything else Paystack offers

The full API is available through one client, for features that aren't wallet-shaped
(subscriptions, split payments, invoices, disputes, terminals, …):

```python
from wallet.paystack import get_paystack_client

paystack = get_paystack_client()
paystack.plans.create(name='Gold', amount=500000, interval='monthly')
paystack.subscriptions.create(customer='CUS_xxx', plan='PLN_xxx')
paystack.subaccounts.create(business_name='Seller', settlement_bank='058',
                            account_number='0123456789', percentage_charge=10)
paystack.splits.create(name='Order split', type='percentage', currency='NGN',
                       subaccounts=[{'subaccount': 'ACCT_xxx', 'share': 80}], bearer_type='account')
paystack.payment_requests.create(customer='CUS_xxx', amount=250000, description='Invoice #7')
paystack.disputes.list(status='awaiting-merchant-feedback')
paystack.transfer_control.balance()
for txn in paystack.paginate('transaction', {'status': 'success'}):
    ...
```

Resources: `transactions`, `splits`, `terminals`, `virtual_terminals`, `customers`,
`direct_debit`, `dedicated_accounts`, `apple_pay`, `subaccounts`, `plans`,
`subscriptions`, `products`, `payment_pages`, `payment_requests`, `settlements`,
`transfer_recipients`, `transfers`, `transfer_control`, `bulk_charges`, `integration`,
`charges`, `disputes`, `refunds`, `verification`, `misc`.

Checkouts can also use split payments directly:
`service.initialize_deposit(wallet, 5000, split_code='SPL_xxx')` or `subaccount='ACCT_xxx'`.
