from decimal import Decimal

import pytest
from django.test import override_settings

from tests.conftest import charge_data, money
from wallet.exceptions import (
    CurrencyMismatchError,
    FeatureDisabled,
    InsufficientFunds,
    InvalidAmount,
    InvalidTransactionState,
    PaystackAPIError,
    RecipientError,
    RecipientNotFound,
    TransactionLimitExceeded,
    WalletLocked,
)
from wallet.models import Transaction
from wallet.services.transaction_service import TransactionService
from wallet.signals import payment_released, transfer_completed

pytestmark = pytest.mark.django_db


@pytest.fixture
def recipient(other_wallet, service):
    service.set_phone_number(other_wallet, '08031234567')
    return other_wallet


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('identifier', ['08031234567', '+2348031234567', '2348031234567', '0803 123 4567',
                                        '8031234567'])
def test_find_recipient_by_phone_in_any_format(service, recipient, identifier):
    assert service.resolve_recipient(identifier) == recipient


def test_find_recipient_by_id_tag_email(service, recipient):
    assert service.resolve_recipient(str(recipient.pk)) == recipient
    assert service.resolve_recipient('bola') == recipient
    assert service.resolve_recipient('@BOLA') == recipient
    assert service.resolve_recipient('Bola@Example.com') == recipient
    assert service.resolve_recipient(recipient) == recipient


def test_explicit_lookup_type(service, recipient):
    assert service.resolve_recipient('08031234567', lookup='phone') == recipient
    with pytest.raises(RecipientNotFound):
        service.resolve_recipient('08031234567', lookup='tag')


def test_numeric_tag_still_resolves(service, recipient):
    service.set_tag(recipient, '12345678')
    assert service.resolve_recipient('12345678') == recipient


def test_lookup_methods_can_be_restricted(service, recipient):
    with override_settings(WALLET_TRANSFER_RECIPIENT_LOOKUP_FIELDS=['id', 'tag']):
        with pytest.raises(RecipientNotFound):
            service.resolve_recipient('08031234567')
        with pytest.raises(RecipientError):
            service.resolve_recipient('08031234567', lookup='phone_number')


def test_unknown_recipient(service, recipient):
    for identifier in ('09099999999', 'nobody', 'x@y.z', '00000000-0000-0000-0000-000000000000', ''):
        with pytest.raises(RecipientNotFound):
            service.resolve_recipient(identifier)


def test_describe_recipient_masks_details(service, recipient):
    details = service.describe_recipient(recipient)
    assert details['name'] == 'Bola A.'
    assert details['phone_number'] == '+234803****567'
    assert details['can_receive'] is True


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------

def test_transfer_by_phone_writes_both_ledger_legs(service, funded_wallet, recipient):
    debit = service.transfer(funded_wallet, '0803 123 4567', 2500, description='rent')
    funded_wallet.refresh_from_db()
    recipient.refresh_from_db()
    assert funded_wallet.balance == money(97500)
    assert recipient.balance == money(2500)

    credit = debit.related_transaction
    assert debit.direction == 'debit' and credit.direction == 'credit'
    assert credit.wallet == recipient and credit.related_transaction == debit
    assert debit.counterparty_wallet == recipient and credit.counterparty_wallet == funded_wallet
    assert debit.balance_after == money(97500) and credit.balance_after == money(2500)
    assert debit.status == credit.status == 'success'


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_INTERNAL_TRANSFER_FEES=True,
                   WALLET_INTERNAL_TRANSFER_FLAT_FEE=10)
@pytest.mark.parametrize('bearer,sender_after,recipient_after', [
    ('customer', 98990, 1000), ('merchant', 99000, 990), ('platform', 99000, 1000), ('split', 98995, 995),
])
def test_transfer_fee_bearers(service, funded_wallet, recipient, bearer, sender_after, recipient_after):
    service.transfer(funded_wallet, recipient, 1000, fee_bearer=bearer)
    funded_wallet.refresh_from_db()
    recipient.refresh_from_db()
    assert funded_wallet.balance == money(sender_after)
    assert recipient.balance == money(recipient_after)


def test_transfer_guards(service, funded_wallet, recipient, wallet):
    with pytest.raises(RecipientError):
        service.transfer(funded_wallet, funded_wallet, 100)
    with pytest.raises(InsufficientFunds):
        service.transfer(funded_wallet, recipient, 1000000)
    with pytest.raises(InvalidAmount):
        service.transfer(funded_wallet, recipient, 0)
    recipient.lock()
    with pytest.raises(WalletLocked):
        service.transfer(funded_wallet, recipient, 100)
    recipient.unlock()
    with override_settings(WALLET_ENABLE_INTERNAL_TRANSFERS=False):
        with pytest.raises(FeatureDisabled):
            service.transfer(funded_wallet, recipient, 100)
    with override_settings(WALLET_MAXIMUM_DAILY_TRANSACTION=1500):
        service.transfer(funded_wallet, recipient, 1000)
        with pytest.raises(TransactionLimitExceeded):
            service.transfer(funded_wallet, recipient, 600)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(99000)


def test_failed_transfer_moves_nothing(service, funded_wallet, recipient):
    recipient.deactivate()
    with pytest.raises(WalletLocked):
        service.transfer(funded_wallet, recipient, 500)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)
    assert not Transaction.objects.filter(transaction_type='transfer').exists()


def test_currency_mismatch(service, funded_wallet, recipient):
    recipient.balance_currency = 'GHS'
    recipient.save()
    recipient.refresh_from_db()
    with pytest.raises(CurrencyMismatchError):
        service.transfer(funded_wallet, recipient, 100)


def test_transfer_signal(service, funded_wallet, recipient, django_capture_on_commit_callbacks):
    seen = []
    transfer_completed.connect(lambda **kw: seen.append(kw['recipient_wallet'].pk), weak=False, dispatch_uid='tc')
    try:
        with django_capture_on_commit_callbacks(execute=True):
            service.transfer(funded_wallet, recipient, 100)
    finally:
        transfer_completed.disconnect(dispatch_uid='tc')
    assert seen == [recipient.pk]


def test_legacy_transfer_name(service, funded_wallet, recipient):
    assert service.transfer_between_wallets(funded_wallet, recipient, 100).is_successful


# ---------------------------------------------------------------------------
# Payments & escrow
# ---------------------------------------------------------------------------

def test_pay_platform(service, funded_wallet):
    txn = service.pay(funded_wallet, 1500, description='Order #1')
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(98500)
    assert txn.transaction_type == 'payment' and txn.is_successful and txn.counterparty_wallet is None


@override_settings(WALLET_ENABLE_FEES=True, WALLET_ENABLE_PAYMENT_FEES=True, WALLET_PAYMENT_PERCENTAGE_FEE=10,
                   WALLET_PAYMENT_FEE_BEARER='merchant')
def test_pay_merchant_with_commission(service, funded_wallet, recipient):
    txn = service.pay(funded_wallet, 1000, merchant_wallet='bola')
    recipient.refresh_from_db()
    assert recipient.balance == money(900)
    assert txn.related_transaction.wallet == recipient


def test_escrow_release(service, funded_wallet, recipient, django_capture_on_commit_callbacks):
    released = []
    payment_released.connect(lambda **kw: released.append(kw['merchant_transaction'].pk), weak=False,
                             dispatch_uid='pr')
    try:
        txn = service.pay(funded_wallet, 3000, merchant_wallet=recipient, escrow=True)
        recipient.refresh_from_db()
        assert txn.status == 'pending' and recipient.balance == money(0)
        assert list(TransactionService.escrowed_payments(recipient)) == [txn]
        with django_capture_on_commit_callbacks(execute=True):
            service.release_payment(txn)
    finally:
        payment_released.disconnect(dispatch_uid='pr')
    txn.refresh_from_db()
    recipient.refresh_from_db()
    assert txn.status == 'success'
    assert recipient.balance == money(3000)
    assert len(released) == 1
    with pytest.raises(InvalidTransactionState):
        service.release_payment(txn)


def test_escrow_cancel_refunds_buyer(service, funded_wallet, recipient):
    txn = service.pay(funded_wallet, 3000, merchant_wallet=recipient, escrow=True)
    TransactionService().cancel_transaction(txn, 'out of stock')
    txn.refresh_from_db()
    funded_wallet.refresh_from_db()
    recipient.refresh_from_db()
    assert txn.status == 'cancelled'
    assert funded_wallet.balance == money(100000)
    assert recipient.balance == money(0)


def test_escrow_needs_merchant(service, funded_wallet):
    from wallet.exceptions import WalletError
    with pytest.raises(WalletError):
        service.pay(funded_wallet, 100, escrow=True)
    with override_settings(WALLET_ENABLE_PAYMENTS=False):
        with pytest.raises(FeatureDisabled):
            service.pay(funded_wallet, 100)


# ---------------------------------------------------------------------------
# Reversals
# ---------------------------------------------------------------------------

def test_reverse_transfer(service, funded_wallet, recipient):
    debit = service.transfer(funded_wallet, recipient, 2000)
    reversal = TransactionService().reverse_transaction(debit, 'sent by mistake')
    funded_wallet.refresh_from_db()
    recipient.refresh_from_db()
    debit.refresh_from_db()
    assert funded_wallet.balance == money(100000)
    assert recipient.balance == money(0)
    assert debit.status == 'reversed' and debit.related_transaction.status == 'reversed'
    assert reversal.direction == 'credit'
    with pytest.raises(InvalidTransactionState):
        TransactionService().reverse_transaction(debit)


def test_reverse_fails_if_recipient_spent_it(service, funded_wallet, recipient, other_user):
    debit = service.transfer(funded_wallet, recipient, 2000)
    service.pay(recipient, 1500)
    with pytest.raises(InsufficientFunds):
        TransactionService().reverse_transaction(debit)
    debit.refresh_from_db()
    assert debit.status == 'success'


def test_reverse_platform_payment(service, funded_wallet):
    txn = service.pay(funded_wallet, 500)
    TransactionService().reverse_transaction(txn)
    funded_wallet.refresh_from_db()
    assert funded_wallet.balance == money(100000)


# ---------------------------------------------------------------------------
# Refunds to card
# ---------------------------------------------------------------------------

@pytest.fixture
def paid_deposit(service, paystack, wallet):
    paystack.add('POST', 'transaction/initialize', {'authorization_url': 'u', 'access_code': 'a'})
    reference = service.initialize_deposit(wallet, 5000)['reference']
    service.process_charge(charge_data(reference, 500000))
    return Transaction.objects.get(reference=reference)


def test_full_refund_debits_and_completes_on_webhook(paystack, paid_deposit):
    paystack.add('POST', 'refund', {'id': 88, 'status': 'pending', 'transaction': {'reference': 'x'}})
    service = TransactionService()
    refund = service.refund_deposit(paid_deposit, reason='customer request')
    wallet = paid_deposit.wallet
    wallet.refresh_from_db()
    assert wallet.balance == money(0)
    assert refund.status == 'pending' and refund.paystack_id == 88
    assert paystack.last_body('refund') == {
        'transaction': paid_deposit.reference, 'amount': 500000, 'currency': 'NGN',
        'merchant_note': 'customer request',
    }
    service.process_refund_event('refund.processing', {'id': 88})
    refund.refresh_from_db()
    assert refund.status == 'processing'
    service.process_refund_event('refund.processed', {'id': 88, 'transaction_reference': paid_deposit.reference})
    refund.refresh_from_db()
    assert refund.status == 'success'


def test_failed_refund_puts_money_back(paystack, paid_deposit):
    paystack.add('POST', 'refund', {'id': 89, 'status': 'pending'})
    service = TransactionService()
    refund = service.refund_deposit(paid_deposit, amount=Decimal('2000'))
    service.process_refund_event('refund.failed', {'transaction_reference': paid_deposit.reference})
    service.process_refund_event('refund.failed', {'id': 89})   # duplicate
    refund.refresh_from_db()
    wallet = paid_deposit.wallet
    wallet.refresh_from_db()
    assert refund.status == 'failed'
    assert wallet.balance == money(5000)


def test_partial_refunds_are_capped(paystack, paid_deposit):
    paystack.add('POST', 'refund', {'id': 90, 'status': 'processed'})
    paystack.add('POST', 'refund', {'id': 91, 'status': 'processed'})
    service = TransactionService()
    assert service.refund_deposit(paid_deposit, amount=3000).status == 'success'
    assert service.refundable_amount(paid_deposit) == Decimal('2000.00')
    with pytest.raises(InvalidAmount):
        service.refund_deposit(paid_deposit, amount=2500)
    service.refund_deposit(paid_deposit, amount=2000)
    with pytest.raises(InvalidAmount):
        service.refund_deposit(paid_deposit)


def test_rejected_refund_restores_balance(paystack, paid_deposit):
    paystack.error('POST', 'refund', 'Transaction has been fully reversed')
    with pytest.raises(PaystackAPIError):
        TransactionService().refund_deposit(paid_deposit)
    wallet = paid_deposit.wallet
    wallet.refresh_from_db()
    assert wallet.balance == money(5000)
    assert Transaction.objects.get(transaction_type='refund').status == 'failed'


def test_only_paid_deposits_are_refundable(service, funded_wallet, recipient):
    transfer = service.transfer(funded_wallet, recipient, 100)
    with pytest.raises(InvalidTransactionState):
        TransactionService().refund_deposit(transfer)


def test_refunds_can_be_disabled(paid_deposit):
    with override_settings(WALLET_ENABLE_CARD_REFUNDS=False):
        with pytest.raises(FeatureDisabled):
            TransactionService().refund_deposit(paid_deposit)


def test_statistics_and_summary(service, funded_wallet, recipient):
    service.transfer(funded_wallet, recipient, 1000)
    stats = TransactionService().get_transaction_statistics(wallet=funded_wallet)
    assert stats['total_count'] == 2
    assert stats['total_debits'] == Decimal('1000')
    summary = TransactionService().get_transaction_summary(wallet=funded_wallet)
    assert summary['overview']['total_credits'] == Decimal('100000')
    assert summary['by_type']['transfer']['count'] == 1


def test_failed_refund_is_visible_on_statement(paystack, paid_deposit):
    paystack.add('POST', 'refund', {'id': 92, 'status': 'pending'})
    service = TransactionService()
    refund = service.refund_deposit(paid_deposit)
    service.process_refund_event('refund.failed', {'id': 92})
    from wallet.services.wallet_service import WalletService
    statement = list(WalletService().get_statement(paid_deposit.wallet))
    assert [(t.transaction_type, t.direction, t.balance_after) for t in statement] == [
        ('deposit', 'credit', money(5000)), ('refund', 'debit', money(0)), ('reversal', 'credit', money(5000)),
    ]
    assert statement[-1].related_transaction == refund
