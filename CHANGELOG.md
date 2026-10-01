# Changelog

## 1.0.0

First complete release. The package was restructured end to end, so upgrading from the
development versions needs a fresh `0001_initial` migration (see
[installation](docs/installation.md#upgrading-from-the-pre-10-code)).

### Money safety

- Every balance change locks the wallet row and writes a ledger entry with `direction`,
  `total_amount`, `balance_after` and a per-wallet `ledger_sequence` (deterministic
  statement order even when timestamps tie). Transfers and wallet payments write a debit
  and a credit leg; failed withdrawals and refunds write a reversal entry.
- Withdrawals debit **before** calling Paystack. Rejections reverse immediately; unknown
  outcomes (timeouts, 5xx) stay pending for reconciliation instead of being refunded
  blindly. `transfer.failed`/`transfer.reversed` return money exactly once.
- Deposits are credited once, idempotently, from the amount Paystack actually collected,
  priced on the channel actually used (foreign cards → international pricing).
- Refunding a deposit now debits the wallet and sends the money back through the Paystack
  Refunds API (previously the wallet was credited).
- Webhooks are de-duplicated by body hash, stored before processing, and replayable;
  processing errors never return non-200 to Paystack.
- Daily limits, per-transaction limits and minimum balance are enforced under the row lock.
- Race-condition tests run against PostgreSQL.

### New

- **Idempotency keys** (`Idempotency-Key` header) on every money-moving endpoint:
  retries replay the first response instead of moving money twice.
- **Rate limiting** per user on lookups, PINs, OTPs, bank resolution and payments
  (`WALLET_THROTTLE_RATES`).
- **Audit log** (`wallet.audit`) of refunds, reversals, escrow release/cancel, deposit
  cancellation and wallet locks, with the acting user stored on the transaction.
- `prune_wallet_data` command/task and retention settings; reconciliation batch size;
  outbound retry window.
- Faster postings: callers holding the row lock skip re-locking (a transfer is ~10
  queries, down from 17).
- `loadtest/`: ledger benchmark (with book-balance checks) and a Locust scenario.

- Complete Paystack API client (`wallet.paystack.PaystackClient`) covering every resource:
  transactions, splits, terminals, virtual terminals, customers, direct debit, dedicated
  accounts, Apple Pay, subaccounts, plans, subscriptions, products, payment pages,
  payment requests, settlements, transfer recipients, transfers, transfer control, bulk
  charges, integration, charges, disputes, refunds, verification, miscellaneous.
- **Phone-number transfers**, plus tag, email and wallet-ID lookup with auto-detection,
  and a recipient preview endpoint with masked details.
- Wallet payments with **escrow** (release / cancel) for marketplaces.
- Fee engine: consistent bearer semantics across operations, customer gross-up,
  international / DVA / mobile-money / educational pricing, tiered withdrawals, marketplace
  commission, database configurations (wallet/global, per channel, tiered, validity
  windows, priority), pluggable calculator, fee quote endpoint, `FeeHistory` audit.
- Optional transaction PIN with lockout.
- Dedicated virtual accounts: create, one-step assign, identity validation, requery,
  deactivate, webhook handling.
- Settlements reuse the withdrawal engine; fixed monthly schedules (short months use their
  last day).
- Domain signals for every money movement, sent on commit.
- Pluggable notifications (`WALLET_NOTIFICATION_BACKENDS`), with email and logging
  backends included.
- Feature switches for every capability.
- Settings resolved lazily from Django settings → environment → defaults;
  `.env.example`, `load_env_file()`, `manage.py wallet_settings`, system checks.
- Management commands: `reconcile_transactions`, `process_settlements`,
  `retry_webhook_deliveries`, `wallet_settings`.
- Checkout callback view that verifies server-side and redirects to your frontend.
- Signed outbound webhook forwarding with per-endpoint event and wallet filters.

### Changed

- UUID primary keys are always used; `WALLET_USE_UUID` was removed (a setting-dependent
  primary key cannot ship working migrations).
- `TransferRecipient` was merged into `BankAccount` (it duplicated the recipient code).
- Celery, xlsxwriter and reportlab are optional extras; unused dependencies removed.
- Admin: ledger data is read-only; changes go through service-backed actions.
- API: dangerous bulk endpoints (arbitrary transaction creation / status changes) removed;
  refunds and reversals are staff-only; escrow cancellation is staff-only; the fee bearer
  can only be chosen by clients when `WALLET_ALLOW_FEE_BEARER_OVERRIDE` is on;
  `X-Forwarded-For` is only trusted with `WALLET_TRUST_X_FORWARDED_FOR`.
- Export query parameter is `export_format` (`format` clashes with DRF content negotiation).
- Changing `WALLET_CURRENCY` no longer generates migrations inside the package.

### Fixed

- Deposit endpoint created two transactions with the same reference.
- `finalize_withdrawal`, `mark_as_failed` and other missing methods were called.
- Three `export` actions were defined outside their viewsets.
- `InvalidWebhookSignature` could not be raised with a message.
- `WebhookEndpoint.timeout` did not exist; delivery attempts had no `request_data`.
- Daily limit counters were double counted by a signal; a `post_save` signal could start
  settlements on every wallet save.
- Excel export failed on timezone-aware datetimes.
