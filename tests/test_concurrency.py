"""
Race-condition tests. They need a database with real row locks
(``SELECT ... FOR UPDATE``), so they are skipped on SQLite. Run them against
PostgreSQL/MySQL with ``pytest --ds=<your postgres settings>``.
"""
import threading
from decimal import Decimal

import pytest
from django.db import connection, connections

from tests.conftest import fund, money
from wallet.exceptions import InsufficientFunds, TransactionLimitExceeded
from wallet.models import Transaction, Wallet
from wallet.services.wallet_service import WalletService

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor == 'sqlite', reason='SQLite has no row-level locking'),
]

THREADS = 8


def race(target, count=THREADS):
    """Run ``target(i)`` in ``count`` threads at once; return (successes, errors)."""
    barrier = threading.Barrier(count)
    results, errors = [], []

    def run(i):
        try:
            barrier.wait()
            results.append(target(i))
        except Exception as exc:  # collected and asserted on by the caller
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


def test_concurrent_transfers_cannot_overspend(user, other_user):
    service = WalletService()
    sender = fund(service.get_wallet(user), 1000)
    receiver = service.get_wallet(other_user)

    successes, errors = race(lambda i: WalletService().transfer(Wallet.objects.get(pk=sender.pk), receiver, 300))

    assert len(successes) == 3                       # 3 x 300 fits in 1000, the 4th does not
    assert all(isinstance(e, InsufficientFunds) for e in errors)
    sender.refresh_from_db()
    receiver.refresh_from_db()
    assert sender.balance == money(100)
    assert receiver.balance == money(900)
    assert sender.balance.amount >= 0


def test_concurrent_debits_respect_daily_limit(user, other_user, settings):
    settings.WALLET_MAXIMUM_DAILY_TRANSACTION = 1000
    service = WalletService()
    sender = fund(service.get_wallet(user), 10000)
    receiver = service.get_wallet(other_user)

    successes, errors = race(lambda i: WalletService().transfer(Wallet.objects.get(pk=sender.pk), receiver, 400))

    assert len(successes) == 2
    assert all(isinstance(e, TransactionLimitExceeded) for e in errors)


def test_duplicate_webhooks_in_parallel_credit_once(user, paystack):
    service = WalletService()
    wallet = service.get_wallet(user)
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = service.initialize_deposit(wallet, 5000)['reference']
    from tests.conftest import charge_data
    data = charge_data(reference, 500000)

    race(lambda i: WalletService().process_charge(dict(data)))

    wallet.refresh_from_db()
    assert wallet.balance == money(5000)
    assert Transaction.objects.filter(reference=reference, status='success').count() == 1


def test_ledger_always_balances_under_mixed_load(user, other_user):
    service = WalletService()
    a = fund(service.get_wallet(user), 5000)
    b = fund(service.get_wallet(other_user), 5000)

    def worker(i):
        source, target = (a, b) if i % 2 else (b, a)
        return WalletService().transfer(Wallet.objects.get(pk=source.pk), Wallet.objects.get(pk=target.pk), 700)

    race(worker, count=12)
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.balance.amount + b.balance.amount == Decimal('10000')   # money is never created or destroyed
    for wallet in (a, b):
        posted = Transaction.objects.filter(wallet=wallet, status='success')
        credits = sum(t.total_amount.amount for t in posted if t.direction == 'credit')
        debits = sum(t.total_amount.amount for t in posted if t.direction == 'debit')
        assert credits - debits == wallet.balance.amount


def test_duplicate_dva_webhooks_in_parallel_credit_once(user):
    """No pre-created row to lock: concurrent inserts must resolve cleanly, not error."""
    from tests.conftest import charge_data

    wallet = WalletService().get_wallet(user)
    wallet.paystack_customer_code = 'CUS_race'
    wallet.save()
    data = charge_data('DVA-RACE-1', 1000000, channel='dedicated_nuban', customer={'customer_code': 'CUS_race'},
                       authorization={'receiver_bank_account_number': '9930000001'})

    successes, errors = race(lambda i: WalletService().process_charge(dict(data)))

    assert errors == []
    assert all(txn is not None for txn in successes)
    wallet.refresh_from_db()
    assert Transaction.objects.filter(reference='DVA-RACE-1').count() == 1
    assert wallet.balance == money(10000)
