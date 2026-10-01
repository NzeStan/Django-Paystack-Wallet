from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from tests.conftest import fund, money
from wallet.exceptions import (
    BankAccountError,
    FeatureDisabled,
    InsufficientFunds,
    InvalidAmount,
    InvalidTransactionState,
    MinimumBalanceViolation,
    PaystackAPIError,
    TransactionLimitExceeded,
)
from wallet.models import BankAccount, Transaction
from wallet.signals import withdrawal_completed, withdrawal_failed

pytestmark = pytest.mark.django_db


def transfer_response(reference, status='pending', code='TRF_abc'):
    return {'reference': reference, 'status': status, 'transfer_code': code, 'id': 555, 'amount': 100}


def start(service, paystack, wallet, bank_account, amount=5000, status='pending', **kwargs):
    reference = kwargs.pop('reference', 'wdr-test-reference-0001')
    paystack.add('POST', 'transfer', transfer_response(reference, status))
    return service.withdraw_to_bank(wallet, amount, bank_account, reference=reference, **kwargs)


def test_debits_before_calling_paystack_and_waits(service, paystack, funded_wallet, bank_account):
    txn, data = start(service, paystack, funded_wallet, bank_account, 5000)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(95000)
    assert txn.status == 'pending' and txn.direction == 'debit'
    assert txn.balance_after == money(95000)
    assert txn.paystack_transfer_code == 'TRF_abc'
    body = paystack.last_body('transfer')
    assert body == {'source': 'balance', 'amount': 500000, 'recipient': 'RCP_test123',
                    'reference': 'wdr-test-reference-0001', 'reason': 'Withdrawal to Test Bank', 'currency': 'NGN'}


def test_immediate_success(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 5000, status='success')
    assert txn.status == 'success'


@override_settings(WALLET_ENABLE_FEES=True)
def test_fee_paid_on_top_by_default(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 10000)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(89975)          # 10,000 + 25 tier fee
    assert txn.total_amount == money(10025)
    assert paystack.last_body('transfer')['amount'] == 1000000


@override_settings(WALLET_ENABLE_FEES=True, WALLET_WITHDRAWAL_FEE_BEARER='merchant')
def test_fee_deducted_from_payout(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 10000)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(90000)
    assert paystack.last_body('transfer')['amount'] == 997500


def test_paystack_rejection_reverses_immediately(service, paystack, funded_wallet, bank_account):
    paystack.error('POST', 'transfer', 'Your balance is not enough to fulfil this request')
    with pytest.raises(PaystackAPIError):
        service.withdraw_to_bank(funded_wallet, 5000, bank_account)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)
    txn = Transaction.objects.get(transaction_type='withdrawal')
    assert txn.status == 'failed'
    reversal = Transaction.objects.get(transaction_type='reversal')
    assert reversal.related_transaction == txn and reversal.direction == 'credit'


def test_unknown_outcome_keeps_money_held(service, paystack, funded_wallet, bank_account):
    paystack.add('POST', 'transfer', status=504, body={'status': False, 'message': 'Gateway timeout'})
    txn, data = service.withdraw_to_bank(funded_wallet, 5000, bank_account)
    assert data['status'] == 'unknown'
    assert txn.status == 'pending' and txn.metadata['needs_reconciliation']
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(95000)


def test_otp_flow(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 5000, status='otp')
    assert txn.requires_otp
    paystack.add('POST', 'transfer/finalize_transfer',
                 transfer_response('wdr-test-reference-0001', status='success'))
    txn = service.finalize_withdrawal(txn, '123456')
    assert txn.status == 'success' and not txn.requires_otp
    assert paystack.last_body('transfer/finalize_transfer') == {'transfer_code': 'TRF_abc', 'otp': '123456'}


def test_wrong_otp_keeps_withdrawal_pending(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 5000, status='otp')
    paystack.error('POST', 'transfer/finalize_transfer', 'Invalid OTP')
    with pytest.raises(PaystackAPIError):
        service.finalize_withdrawal(txn, '000000')
    txn.refresh_from_db()
    assert txn.status == 'pending' and txn.requires_otp
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(95000)


def test_resend_and_cancel_otp(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 5000, status='otp')
    paystack.add('POST', 'transfer/resend_otp', {})
    service.resend_withdrawal_otp(txn)
    assert paystack.last_body('transfer/resend_otp') == {'transfer_code': 'TRF_abc', 'reason': 'transfer'}
    service.cancel_otp_withdrawal(txn)
    txn.refresh_from_db()
    funded_wallet.refresh_from_db()
    assert txn.status == 'failed'
    assert funded_wallet.balance == money(100000)


def test_finalize_requires_pending_withdrawal(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account, 5000, status='success')
    with pytest.raises(InvalidTransactionState):
        service.finalize_withdrawal(txn, '1')


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def test_transfer_success_webhook(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account)
    service.process_transfer_event('transfer.success', transfer_response(txn.reference))
    txn.refresh_from_db()
    assert txn.status == 'success'


@pytest.mark.parametrize('event,final', [('transfer.failed', 'failed'), ('transfer.reversed', 'reversed')])
def test_failed_or_reversed_transfer_refunds_exactly_once(service, paystack, funded_wallet, bank_account, event,
                                                          final):
    txn, _ = start(service, paystack, funded_wallet, bank_account)
    payload = transfer_response(txn.reference)
    service.process_transfer_event(event, payload)
    service.process_transfer_event(event, payload)
    funded_wallet.refresh_from_db()
    txn.refresh_from_db()
    assert funded_wallet.balance == money(100000)
    assert txn.status == final
    assert Transaction.objects.filter(transaction_type='reversal').count() == 1


def test_reversal_after_success(service, paystack, funded_wallet, bank_account):
    """Banks can bounce a transfer after Paystack reported success."""
    txn, _ = start(service, paystack, funded_wallet, bank_account, status='success')
    service.process_transfer_event('transfer.reversed', transfer_response(txn.reference))
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)


def test_transfer_event_matched_by_transfer_code(service, paystack, funded_wallet, bank_account):
    start(service, paystack, funded_wallet, bank_account)
    txn = service.process_transfer_event('transfer.success', {'transfer_code': 'TRF_abc'})
    assert txn.status == 'success'
    assert service.process_transfer_event('transfer.success', {'reference': 'unknown'}) is None


def test_signals(service, paystack, funded_wallet, bank_account, django_capture_on_commit_callbacks):
    seen = []
    withdrawal_completed.connect(lambda **kw: seen.append('completed'), weak=False, dispatch_uid='w1')
    withdrawal_failed.connect(lambda **kw: seen.append(('failed', kw['reversed'])), weak=False, dispatch_uid='w2')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            ok, _ = start(service, paystack, funded_wallet, bank_account, reference='wdr-test-reference-0002')
            bad, _ = start(service, paystack, funded_wallet, bank_account, reference='wdr-test-reference-0003')
            service.process_transfer_event('transfer.success', transfer_response(ok.reference))
            service.process_transfer_event('transfer.reversed', transfer_response(bad.reference))
    finally:
        withdrawal_completed.disconnect(dispatch_uid='w1')
        withdrawal_failed.disconnect(dispatch_uid='w2')
    assert seen == ['completed', ('failed', True)]


# ---------------------------------------------------------------------------
# Verification & reconciliation
# ---------------------------------------------------------------------------

def test_verify_withdrawal(service, paystack, funded_wallet, bank_account):
    txn, _ = start(service, paystack, funded_wallet, bank_account)
    paystack.add('GET', f'transfer/verify/{txn.reference}', transfer_response(txn.reference, 'success'))
    assert service.verify_withdrawal(txn).status == 'success'


def test_transfer_never_created_is_refunded(service, paystack, funded_wallet, bank_account):
    paystack.add('POST', 'transfer', status=500, body={'status': False, 'message': 'Server error'})
    txn, _ = service.withdraw_to_bank(funded_wallet, 5000, bank_account)
    paystack.error('GET', f'transfer/verify/{txn.reference}', 'Transfer not found', status=404)
    Transaction.objects.filter(pk=txn.pk).update(created_at=timezone.now() - timedelta(hours=1))
    assert service.reconcile_pending_withdrawals(older_than_minutes=5) == 1
    txn.refresh_from_db()
    funded_wallet.refresh_from_db()
    assert txn.status == 'failed'
    assert funded_wallet.balance == money(100000)


def test_reconcile_skips_otp_and_recent(service, paystack, funded_wallet, bank_account):
    start(service, paystack, funded_wallet, bank_account, status='otp')
    assert service.reconcile_pending_withdrawals(older_than_minutes=0) == 0


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def test_insufficient_funds_leaves_nothing_behind(service, wallet, bank_account):
    fund(wallet, 1000)
    with pytest.raises(InsufficientFunds):
        service.withdraw_to_bank(wallet, 5000, bank_account)
    assert not Transaction.objects.filter(transaction_type='withdrawal').exists()


@override_settings(WALLET_MINIMUM_BALANCE=1000)
def test_minimum_balance_respected(service, wallet, bank_account):
    fund(wallet, 5000)
    with pytest.raises(MinimumBalanceViolation):
        service.withdraw_to_bank(wallet, 4500, bank_account)


@override_settings(WALLET_MAXIMUM_DAILY_TRANSACTION=8000)
def test_daily_limit_counts_pending_withdrawals(service, paystack, funded_wallet, bank_account):
    start(service, paystack, funded_wallet, bank_account, 5000, reference='wdr-test-reference-0004')
    with pytest.raises(TransactionLimitExceeded):
        start(service, paystack, funded_wallet, bank_account, 5000, reference='wdr-test-reference-0005')


def test_minimum_withdrawal_and_reference_rules(service, funded_wallet, bank_account):
    with pytest.raises(InvalidAmount):
        service.withdraw_to_bank(funded_wallet, 50, bank_account)
    with pytest.raises(InvalidAmount):
        service.withdraw_to_bank(funded_wallet, 5000, bank_account, reference='UPPER-CASE-REFERENCE')


def test_bank_account_must_belong_to_wallet(service, funded_wallet, other_wallet, bank):
    theirs = BankAccount.objects.create(wallet=other_wallet, bank=bank, account_number='1111111111',
                                        account_name='B', paystack_recipient_code='RCP_other')
    with pytest.raises(BankAccountError):
        service.withdraw_to_bank(funded_wallet, 5000, theirs)
    theirs.wallet = funded_wallet
    theirs.is_active = False
    theirs.save()
    with pytest.raises(BankAccountError):
        service.withdraw_to_bank(funded_wallet, 5000, theirs)
    with pytest.raises(BankAccountError):
        service.withdraw_to_bank(funded_wallet, 5000, None)


def test_recipient_created_on_first_withdrawal(service, paystack, funded_wallet, bank):
    account = BankAccount.objects.create(wallet=funded_wallet, bank=bank, account_number='2222222222',
                                         account_name='ADA OBI')
    paystack.add('POST', 'transferrecipient', {'recipient_code': 'RCP_new', 'id': 9, 'details': {}})
    start(service, paystack, funded_wallet, account, 1000)
    account.refresh_from_db()
    assert account.paystack_recipient_code == 'RCP_new'
    assert paystack.last_body('transfer')['recipient'] == 'RCP_new'


def test_withdrawals_can_be_disabled(service, funded_wallet, bank_account):
    with override_settings(WALLET_ENABLE_WITHDRAWALS=False):
        with pytest.raises(FeatureDisabled):
            service.withdraw_to_bank(funded_wallet, 1000, bank_account)


def test_locked_wallet_cannot_withdraw(service, funded_wallet, bank_account):
    funded_wallet.lock()
    from wallet.exceptions import WalletLocked
    with pytest.raises(WalletLocked):
        service.withdraw_to_bank(funded_wallet, 1000, bank_account)
    assert Decimal(funded_wallet.balance.amount) == Decimal('100000')
