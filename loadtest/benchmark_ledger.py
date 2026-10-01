"""
Ledger throughput benchmark - run it against your production-like database.

It measures how many wallet-to-wallet transfers per second the ledger sustains
with many threads, in two shapes:

* spread   - transfers between many independent wallet pairs (typical app traffic)
* hotspot  - every transfer pays ONE wallet (a big seller / platform wallet)

and then checks the books still balance. It creates its own users and wallets
(usernames start with ``bench-``) and deletes them afterwards.

    DJANGO_SETTINGS_MODULE=myproject.settings python loadtest/benchmark_ledger.py \
        --threads 16 --transfers 2000

Use PostgreSQL/MySQL. SQLite serialises all writes and has no row locks, so its
numbers mean nothing for production.
"""
import argparse
import os
import sys
import threading
import time
from decimal import Decimal

sys.path.insert(0, os.getcwd())

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection, connections  # noqa: E402
from django.db.models import Sum  # noqa: E402

from wallet.models import Transaction, Wallet  # noqa: E402
from wallet.services.wallet_service import WalletService  # noqa: E402

PREFIX = 'bench-'


def make_wallets(count, funds):
    User = get_user_model()
    service = WalletService()
    wallets = []
    for index in range(count):
        user = User.objects.create_user(username=f'{PREFIX}{index}', email=f'{PREFIX}{index}@bench.invalid')
        wallet = service.get_wallet(user)
        service.credit_wallet(wallet, funds, description='benchmark funding')
        wallets.append(wallet.pk)
    return wallets


def run(threads, jobs, work):
    """Run ``work(job)`` for every job across ``threads`` threads. Returns (seconds, errors)."""
    lock = threading.Lock()
    queue = list(jobs)
    errors = []

    def worker():
        service = WalletService()
        while True:
            with lock:
                if not queue:
                    break
                job = queue.pop()
            try:
                work(service, job)
            except Exception as exc:  # counted and reported
                errors.append(exc)
        connections.close_all()

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    started = time.perf_counter()
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()
    return time.perf_counter() - started, errors


def transfer(service, job):
    source, destination = job
    service.transfer(Wallet.objects.get(pk=source), Wallet.objects.get(pk=destination), Decimal('1.00'))


def check_books(wallet_ids, expected_total):
    total = Wallet.objects.filter(pk__in=wallet_ids).aggregate(total=Sum('balance'))['total']
    assert total == expected_total, f"Money created or destroyed: {total} != {expected_total}"
    for wallet in Wallet.objects.filter(pk__in=wallet_ids):
        posted = Transaction.objects.filter(wallet=wallet, ledger_sequence__isnull=False)
        credits = posted.filter(direction='credit').aggregate(s=Sum('total_amount'))['s'] or 0
        debits = posted.filter(direction='debit').aggregate(s=Sum('total_amount'))['s'] or 0
        assert credits - debits == wallet.balance.amount, f"Ledger mismatch on {wallet.pk}"
        count = posted.count()
        assert wallet.ledger_sequence == count, f"Sequence gap on {wallet.pk}"


def cleanup():
    User = get_user_model()
    wallets = Wallet.objects.filter(user__username__startswith=PREFIX)
    Transaction.objects.filter(wallet__in=wallets).update(related_transaction=None)
    Transaction.objects.filter(wallet__in=wallets).delete()
    User.objects.filter(username__startswith=PREFIX).delete()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--threads', type=int, default=16)
    parser.add_argument('--transfers', type=int, default=2000)
    parser.add_argument('--wallets', type=int, default=64)
    args = parser.parse_args()

    print(f"Database: {connection.vendor} | threads={args.threads} transfers={args.transfers} "
          f"wallets={args.wallets}")
    if connection.vendor == 'sqlite':
        print("WARNING: SQLite has no row locks - results are not meaningful for production.")

    cleanup()
    funds = Decimal(args.transfers)
    try:
        wallets = make_wallets(args.wallets, funds)
        expected = funds * len(wallets)

        pairs = [(wallets[i % len(wallets)], wallets[(i + 1) % len(wallets)]) for i in range(args.transfers)]
        seconds, errors = run(args.threads, pairs, transfer)
        print(f"spread : {args.transfers / seconds:8.1f} transfers/s  ({seconds:.2f}s, errors={len(errors)})")
        check_books(wallets, expected)

        hot = wallets[0]
        into_hot = [(wallets[1 + i % (len(wallets) - 1)], hot) for i in range(args.transfers)]
        seconds, errors = run(args.threads, into_hot, transfer)
        print(f"hotspot: {args.transfers / seconds:8.1f} transfers/s  ({seconds:.2f}s, errors={len(errors)})")
        check_books(wallets, expected)
        print("Books balance: no money created or destroyed, ledgers and sequences consistent.")
    finally:
        cleanup()


if __name__ == '__main__':
    main()
