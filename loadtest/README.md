# Load testing

Two tools, for two questions.

## 1. How fast is the ledger on *my* database? (`benchmark_ledger.py`)

Runs thousands of concurrent wallet-to-wallet transfers directly through the service
layer, then proves the books still balance (no money created or destroyed, every
wallet's ledger matches its balance, no gaps in ledger sequence numbers).

```bash
DJANGO_SETTINGS_MODULE=myproject.settings python loadtest/benchmark_ledger.py --threads 16 --transfers 5000
```

It reports two shapes of traffic:

- **spread**: transfers between many independent wallets (normal app traffic)
- **hotspot**: every transfer pays one wallet (a very busy seller or platform wallet)

Reference numbers from development (Windows laptop, embedded PostgreSQL, benchmark
client in a single Python process, 256 wallets):

| Threads | spread | hotspot |
| --- | --- | --- |
| 1 | ~185/s | ~170/s |
| 4 | ~235/s | ~220/s |
| 16 | ~215/s | ~200/s |

All runs finished with zero errors and balanced books. The plateau is the single
client process and the laptop's disk (with `synchronous_commit=off`, which you should
**not** use for money, it rises about 25%), not the ledger itself. A transfer is about
10 SQL queries in one database transaction. On server hardware, with several app
processes, expect considerably more. Measure yours.

For scale: 200 transfers per second is about 17 million per day. Throughput is per
wallet pair, so independent users don't queue behind each other. A single very busy
wallet does queue, because its row is locked for each posting. That is the ceiling to
watch for a marketplace with one dominant seller or a platform fee wallet.

Only run it against PostgreSQL or MySQL; SQLite numbers are meaningless. It creates
`bench-*` users and deletes them afterwards, so point it at a staging database, not
production.

## 2. How does the whole stack hold up? (`locustfile.py`)

HTTP load through your real deployment: web servers, auth, throttles, database.

```bash
pip install locust
LOADTEST_TOKENS=tok1,tok2 LOADTEST_RECIPIENTS=ada,bola \
  locust -f loadtest/locustfile.py --host https://staging.example.com
```

It exercises balance, history, fee quotes, recipient lookup and idempotent internal
transfers, none of which reach Paystack. Raise `WALLET_THROTTLE_RATES` on staging first,
or you'll mostly be measuring the rate limiter.

## Production checklist for high volume

- PostgreSQL (or MySQL/InnoDB), never SQLite. Put **PgBouncer** (transaction pooling)
  or Django's connection pooling in front of it.
- **Redis** as `CACHES['default']` so rate limits are shared by every server.
- **Celery** (`WALLET_USE_CELERY=True`) so webhooks are acknowledged instantly and
  processed by workers. Paystack retries slow webhook endpoints.
- Schedule `reconcile_transactions` (every 5-10 minutes), `prune_wallet_data` (daily)
  and, if you use them, `process_settlements`. Raise `WALLET_RECONCILE_BATCH_SIZE`
  if reconciliation falls behind.
- Clients send an `Idempotency-Key` on every money-moving POST
  (`WALLET_REQUIRE_IDEMPOTENCY_KEY=True` to enforce it).
- Route the `wallet.audit` logger to durable storage.
- The transaction table is append-only; plan partitioning or archiving by date once it
  reaches hundreds of millions of rows.
