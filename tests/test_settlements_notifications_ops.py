from datetime import timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from tests.conftest import charge_data, fund, money
from tests.helpers import RecordingBackend
from wallet.checks import check_wallet_settings
from wallet.exceptions import SettlementError
from wallet.models import Card, Settlement, SettlementSchedule
from wallet.services.settlement_service import SettlementService

pytestmark = pytest.mark.django_db


def transfer(reference, status='pending'):
    return {'reference': reference, 'status': status, 'transfer_code': f'TRF_{reference[-4:]}'}


def mock_transfer(paystack, status='pending'):
    """Answer POST /transfer echoing the reference we sent."""
    def callback(request):
        import json
        body = json.loads(request.body)
        return 200, {}, json.dumps({'status': True, 'data': transfer(body['reference'], status)})
    paystack.rsps.add_callback('POST', 'https://api.paystack.co/transfer', callback=callback)


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

def test_settlement_follows_the_withdrawal(paystack, funded_wallet, bank_account):
    mock_transfer(paystack)
    service = SettlementService()
    settlement = service.create_settlement(funded_wallet, bank_account, 20000)
    assert settlement.status == 'processing'
    assert settlement.transaction.transaction_type == 'withdrawal'
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(80000)

    from wallet.services.withdrawal_service import WithdrawalService
    WithdrawalService().process_transfer_event('transfer.success', transfer(settlement.transaction.reference))
    settlement.refresh_from_db()
    assert settlement.status == 'success' and settlement.settled_at


def test_settlement_otp_and_failure(paystack, funded_wallet, bank_account):
    mock_transfer(paystack, status='otp')
    service = SettlementService()
    settlement = service.create_settlement(funded_wallet, bank_account, 1000)
    assert settlement.status == 'pending' and settlement.requires_otp
    paystack.add('POST', 'transfer/finalize_transfer', {'status': 'failed', 'reason': 'OTP expired',
                                                         'reference': settlement.transaction.reference})
    service.finalize_settlement(settlement, '123456')
    assert settlement.status == 'failed'
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)


def test_settlement_rejected_upfront(paystack, wallet, bank_account):
    fund(wallet, 500)
    with pytest.raises(SettlementError):
        SettlementService().create_settlement(wallet, bank_account, 1000)
    assert Settlement.objects.get().status == 'failed'


def test_retry_failed_settlement(paystack, funded_wallet, bank_account):
    paystack.error('POST', 'transfer', 'Recipient bank unavailable')
    service = SettlementService()
    with pytest.raises(SettlementError):
        service.create_settlement(funded_wallet, bank_account, 1000)
    settlement = Settlement.objects.get()
    mock_transfer(paystack, status='success')
    settlement = service.retry_settlement(settlement)
    assert settlement.status == 'success'
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(99000)


def test_due_schedules_pay_out_available_balance(paystack, funded_wallet, bank_account, settings):
    settings.WALLET_MINIMUM_BALANCE = 1000
    mock_transfer(paystack)
    schedule = SettlementSchedule.objects.create(wallet=funded_wallet, bank_account=bank_account,
                                                 schedule_type='daily', maximum_amount=money(60000))
    SettlementSchedule.objects.filter(pk=schedule.pk).update(next_settlement=timezone.now() - timedelta(minutes=1))
    assert SettlementService().process_due_settlements() == 1
    schedule.refresh_from_db()
    assert schedule.next_settlement > timezone.now() and schedule.last_settlement
    assert Settlement.objects.get().amount == money(60000)
    assert SettlementService().process_due_settlements() == 0


def test_threshold_schedule_runs_after_credit(paystack, wallet, bank_account, settings,
                                              django_capture_on_commit_callbacks):
    settings.WALLET_AUTO_SETTLEMENT = True
    mock_transfer(paystack)
    SettlementService().create_settlement_schedule(wallet, bank_account, 'threshold', amount_threshold=10000,
                                                   minimum_amount=1000)
    with django_capture_on_commit_callbacks(execute=True):
        fund(wallet, 8000)
    assert not Settlement.objects.exists()
    with django_capture_on_commit_callbacks(execute=True):
        fund(wallet, 7000)
    settlement = Settlement.objects.get()
    assert settlement.amount == money(5000)          # everything above the 10,000 threshold
    wallet.refresh_from_db()
    assert wallet.balance == money(10000)


def test_schedule_creation_validates(wallet, bank_account, other_wallet):
    service = SettlementService()
    with pytest.raises(Exception):
        service.create_settlement_schedule(wallet, bank_account, 'weekly')
    with pytest.raises(SettlementError):
        service.create_settlement_schedule(other_wallet, bank_account, 'daily')
    schedule = service.create_settlement_schedule(wallet, bank_account, 'monthly', day_of_month=31)
    assert schedule.next_settlement is not None


def test_settlement_stats(paystack, funded_wallet, bank_account):
    mock_transfer(paystack, status='success')
    service = SettlementService()
    service.create_settlement(funded_wallet, bank_account, 1000)
    stats = service.get_settlement_stats(wallet=funded_wallet)
    assert stats['total_count'] == 1 and stats['success_rate'] == 100.0
    assert service.get_settlement_summary(funded_wallet)['settlement_count'] == 1
    assert service.get_top_settlement_destinations(funded_wallet)[0]['settlement_count'] == 1


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _pay(service, paystack, wallet, amount=5000):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = service.initialize_deposit(wallet, amount)['reference']
    service.process_charge(charge_data(reference, amount * 100))
    return reference


def test_no_notifications_without_backends(service, paystack, wallet, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        _pay(service, paystack, wallet)
    assert mail.outbox == []


@override_settings(WALLET_NOTIFICATION_BACKENDS=['wallet.notifications.backends.EmailNotificationBackend'])
def test_email_backend(service, paystack, wallet, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        reference = _pay(service, paystack, wallet)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ['ada@example.com']
    assert message.subject == 'Your wallet has been funded'
    assert reference in message.body and '5,000.00' in message.body


@override_settings(WALLET_NOTIFICATION_BACKENDS=['tests.helpers.ExplodingBackend', 'tests.helpers.RecordingBackend'])
def test_custom_backends_and_failure_isolation(service, funded_wallet, other_wallet,
                                               django_capture_on_commit_callbacks):
    RecordingBackend.sent.clear()
    with django_capture_on_commit_callbacks(execute=True):
        service.transfer(funded_wallet, other_wallet, 700)
    events = [(event, user) for event, user, _ in RecordingBackend.sent]
    assert ('transfer_sent', funded_wallet.user_id) in events
    assert ('transfer_received', other_wallet.user_id) in events


# ---------------------------------------------------------------------------
# Tasks, commands, checks
# ---------------------------------------------------------------------------

def test_tasks_run_inline(paystack, wallet, card):
    from wallet import tasks
    card.expiry_year = '2001'
    card.save()
    assert tasks.check_expired_cards_task() == 1
    assert not Card.objects.get(pk=card.pk).is_active
    assert tasks.reconcile_transactions_task() == {'deposits': 0, 'withdrawals': 0}
    assert tasks.process_due_settlements_task() == 0
    assert tasks.retry_failed_webhook_deliveries_task() == 0
    paystack.add('POST', 'customer', {'customer_code': 'CUS_t', 'id': 1})
    assert tasks.setup_paystack_customer_task(str(wallet.pk)) is True


def test_management_commands(paystack, wallet):
    out = StringIO()
    paystack.add('GET', 'bank', [{'name': 'Kuda', 'code': '50211', 'currency': 'NGN', 'type': 'nuban'}], meta={})
    call_command('sync_banks', stdout=out)
    assert 'Created 1' in out.getvalue()
    call_command('reconcile_transactions', '--older-than', '5', stdout=out)
    call_command('process_settlements', stdout=out)
    call_command('retry_webhook_deliveries', stdout=out)
    call_command('backfill_fee_history', '--dry-run', stdout=out)
    call_command('wallet_settings', stdout=out)
    assert 'WALLET_CURRENCY' in out.getvalue()
    call_command('wallet_settings', '--json', stdout=out)


def test_system_checks():
    assert check_wallet_settings(None) == []
    with override_settings(PAYSTACK_SECRET_KEY='', WALLET_DEFAULT_FEE_BEARER='nobody',
                           WALLET_FEE_SPLIT_CUSTOMER_PERCENTAGE=10,
                           WALLET_TRANSFER_RECIPIENT_LOOKUP_FIELDS=['id', 'bvn'],
                           WALLET_NOTIFICATION_BACKENDS=['nope.Backend']):
        ids = {message.id for message in check_wallet_settings(None)}
    assert {'wallet.W001', 'wallet.E003', 'wallet.E004', 'wallet.E005', 'wallet.E007'} <= ids
    with override_settings(PAYSTACK_SECRET_KEY='sk_live_dummy-key-for-tests', PAYSTACK_PUBLIC_KEY='pk_test_dummy-key-for-tests', DEBUG=True):
        ids = {message.id for message in check_wallet_settings(None)}
    assert {'wallet.W003', 'wallet.W004'} <= ids


def test_migrations_are_in_sync():
    out = StringIO()
    call_command('makemigrations', 'wallet', '--check', '--dry-run', stdout=out)
    with override_settings(WALLET_CURRENCY='GHS'):
        call_command('makemigrations', 'wallet', '--check', '--dry-run', stdout=out)
