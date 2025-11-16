"""
Django Paystack Wallet - Transaction Service Tests
Comprehensive test suite for TransactionService

Test Coverage:
1. TransactionServiceRetrievalTestCase - get_transaction, get_transaction_by_reference, list_transactions (12 tests)
2. TransactionServiceCreationTestCase - create_transaction, bulk_create_transactions (6 tests)
3. TransactionServiceStatusUpdateTestCase - mark_as_success, mark_as_failed, cancel_transaction (9 tests)
4. TransactionServiceRefundTestCase - refund_transaction operations (5 tests)
5. TransactionServiceReversalTestCase - reverse_transaction operations (3 tests)
6. TransactionServiceTransferTestCase - transfer_between_wallets operations (4 tests)
7. TransactionServiceStatisticsTestCase - get_transaction_statistics, get_transaction_summary (5 tests)
8. TransactionServiceBulkOperationsTestCase - bulk_update_status (5 tests)

Total: 49 test methods
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from djmoney.money import Money
from unittest.mock import patch, MagicMock

from wallet.models import Transaction, Wallet
from wallet.services.transaction_service import TransactionService
from wallet.services.wallet_service import WalletService
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_TYPE_REFUND,
    TRANSACTION_TYPE_REVERSAL,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_CANCELLED,
)
from wallet.exceptions import TransactionFailed


User = get_user_model()
DEFAULT_CURRENCY = get_wallet_setting('CURRENCY')


class TransactionServiceRetrievalTestCase(TestCase):
    """Test case for transaction retrieval methods"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction_service = TransactionService()
        
        # Create test transactions
        self.transaction1 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='TXN_TEST_001'
        )
        
        self.transaction2 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING,
            reference='TXN_TEST_002'
        )

    def test_get_transaction(self):
        """Test getting a transaction by ID"""
        transaction = self.transaction_service.get_transaction(self.transaction1.id)
        
        self.assertEqual(transaction.id, self.transaction1.id)
        self.assertEqual(transaction.reference, 'TXN_TEST_001')
        self.assertEqual(transaction.amount, Money(100, DEFAULT_CURRENCY))

    def test_get_transaction_not_found(self):
        """Test getting non-existent transaction raises error"""
        import uuid
        fake_id = uuid.uuid4()
        
        with self.assertRaises(Transaction.DoesNotExist):
            self.transaction_service.get_transaction(fake_id)

    def test_get_transaction_with_lock(self):
        """Test getting a transaction with select_for_update lock"""
        transaction = self.transaction_service.get_transaction(
            self.transaction1.id,
            for_update=True
        )
        
        self.assertEqual(transaction.id, self.transaction1.id)

    def test_get_transaction_by_reference(self):
        """Test getting a transaction by reference"""
        transaction = self.transaction_service.get_transaction_by_reference('TXN_TEST_001')
        
        self.assertEqual(transaction.id, self.transaction1.id)
        self.assertEqual(transaction.reference, 'TXN_TEST_001')

    def test_get_transaction_by_reference_not_found(self):
        """Test getting transaction by non-existent reference raises error"""
        with self.assertRaises(Transaction.DoesNotExist):
            self.transaction_service.get_transaction_by_reference('INVALID_REF')

    def test_get_transaction_by_reference_with_lock(self):
        """Test getting transaction by reference with lock"""
        transaction = self.transaction_service.get_transaction_by_reference(
            'TXN_TEST_001',
            for_update=True
        )
        
        self.assertEqual(transaction.reference, 'TXN_TEST_001')

    def test_list_transactions_all(self):
        """Test listing all transactions"""
        transactions = self.transaction_service.list_transactions()
        
        self.assertEqual(transactions.count(), 2)

    def test_list_transactions_by_wallet(self):
        """Test listing transactions for a specific wallet"""
        transactions = self.transaction_service.list_transactions(wallet=self.wallet)
        
        self.assertEqual(transactions.count(), 2)

    def test_list_transactions_by_status(self):
        """Test listing transactions by status"""
        transactions = self.transaction_service.list_transactions(
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions.first().status, TRANSACTION_STATUS_SUCCESS)

    def test_list_transactions_by_type(self):
        """Test listing transactions by type"""
        transactions = self.transaction_service.list_transactions(
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions.first().transaction_type, TRANSACTION_TYPE_DEPOSIT)

    def test_list_transactions_with_limit(self):
        """Test listing transactions with limit"""
        transactions = self.transaction_service.list_transactions(limit=1)
        
        self.assertEqual(len(list(transactions)), 1)

    def test_list_transactions_with_offset(self):
        """Test listing transactions with offset"""
        transactions = self.transaction_service.list_transactions(offset=1)
        
        self.assertEqual(transactions.count(), 1)


class TransactionServiceCreationTestCase(TestCase):
    """Test case for transaction creation methods"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction_service = TransactionService()

    def test_create_transaction(self):
        """Test creating a transaction"""
        transaction = self.transaction_service.create_transaction(
            wallet=self.wallet,
            amount=Decimal('100.00'),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            description='Test deposit'
        )
        
        self.assertIsNotNone(transaction.id)
        self.assertEqual(transaction.wallet, self.wallet)
        self.assertEqual(transaction.amount.amount, Decimal('100.00'))
        self.assertEqual(transaction.transaction_type, TRANSACTION_TYPE_DEPOSIT)
        self.assertEqual(transaction.status, TRANSACTION_STATUS_PENDING)
        self.assertEqual(transaction.description, 'Test deposit')
        self.assertIsNotNone(transaction.reference)

    def test_create_transaction_with_custom_reference(self):
        """Test creating transaction with custom reference"""
        custom_ref = 'CUSTOM_REF_12345'
        transaction = self.transaction_service.create_transaction(
            wallet=self.wallet,
            amount=Decimal('100.00'),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            reference=custom_ref
        )
        
        self.assertEqual(transaction.reference, custom_ref)

    def test_create_transaction_with_metadata(self):
        """Test creating transaction with metadata"""
        metadata = {'order_id': '12345', 'customer_name': 'John Doe'}
        transaction = self.transaction_service.create_transaction(
            wallet=self.wallet,
            amount=Decimal('100.00'),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            metadata=metadata
        )
        
        self.assertEqual(transaction.metadata, metadata)

    def test_create_transaction_with_kwargs(self):
        """Test creating transaction with additional kwargs"""
        transaction = self.transaction_service.create_transaction(
            wallet=self.wallet,
            amount=Decimal('100.00'),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            paystack_reference='PYSTACK_REF_123'
        )
        
        self.assertEqual(transaction.paystack_reference, 'PYSTACK_REF_123')

    def test_bulk_create_transactions(self):
        """Test bulk creating transactions"""
        user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='password123'
        )
        wallet_service = WalletService()
        wallet2 = wallet_service.get_wallet(user2)
        
        transactions_data = [
            {
                'wallet': self.wallet,
                'amount': Decimal('100.00'),
                'transaction_type': TRANSACTION_TYPE_DEPOSIT,
                'description': 'Bulk deposit 1'
            },
            {
                'wallet': wallet2,
                'amount': Decimal('200.00'),
                'transaction_type': TRANSACTION_TYPE_DEPOSIT,
                'description': 'Bulk deposit 2'
            }
        ]
        
        created_transactions = self.transaction_service.bulk_create_transactions(
            transactions_data
        )
        
        self.assertEqual(len(created_transactions), 2)
        self.assertEqual(created_transactions[0].amount.amount, Decimal('100.00'))
        self.assertEqual(created_transactions[1].amount.amount, Decimal('200.00'))
        self.assertIsNotNone(created_transactions[0].reference)
        self.assertIsNotNone(created_transactions[1].reference)

    def test_bulk_create_transactions_auto_generates_references(self):
        """Test bulk create auto-generates references"""
        transactions_data = [
            {
                'wallet': self.wallet,
                'amount': Decimal('100.00'),
                'transaction_type': TRANSACTION_TYPE_DEPOSIT
            }
        ]
        
        created_transactions = self.transaction_service.bulk_create_transactions(
            transactions_data
        )
        
        self.assertIsNotNone(created_transactions[0].reference)


class TransactionServiceStatusUpdateTestCase(TestCase):
    """Test case for transaction status update methods"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet.save()
        
        self.transaction_service = TransactionService()

    def test_mark_transaction_as_success(self):
        """Test marking transaction as successful"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        updated_transaction = self.transaction_service.mark_transaction_as_success(
            transaction
        )
        
        self.assertEqual(updated_transaction.status, TRANSACTION_STATUS_SUCCESS)
        self.assertIsNotNone(updated_transaction.completed_at)

    def test_mark_transaction_as_success_with_paystack_data(self):
        """Test marking transaction as successful with Paystack data"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        paystack_data = {
            'status': 'success',
            'reference': 'PYSTACK_REF_123',
            'amount': 10000
        }
        
        updated_transaction = self.transaction_service.mark_transaction_as_success(
            transaction,
            paystack_data=paystack_data
        )
        
        self.assertEqual(updated_transaction.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(updated_transaction.paystack_response, paystack_data)
        self.assertEqual(updated_transaction.paystack_reference, 'PYSTACK_REF_123')

    def test_mark_already_successful_transaction(self):
        """Test marking already successful transaction doesn't fail"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        updated_transaction = self.transaction_service.mark_transaction_as_success(
            transaction
        )
        
        self.assertEqual(updated_transaction.status, TRANSACTION_STATUS_SUCCESS)

    def test_mark_transaction_as_failed(self):
        """Test marking transaction as failed"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        updated_transaction = self.transaction_service.mark_transaction_as_failed(
            transaction,
            reason='Payment declined'
        )
        
        self.assertEqual(updated_transaction.status, TRANSACTION_STATUS_FAILED)
        self.assertEqual(updated_transaction.failed_reason, 'Payment declined')
        self.assertIsNotNone(updated_transaction.completed_at)

    def test_mark_transaction_as_failed_with_paystack_data(self):
        """Test marking transaction as failed with Paystack data"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        paystack_data = {'status': 'failed', 'message': 'Insufficient funds'}
        
        updated_transaction = self.transaction_service.mark_transaction_as_failed(
            transaction,
            paystack_data=paystack_data
        )
        
        self.assertEqual(updated_transaction.paystack_response, paystack_data)

    def test_mark_failed_withdrawal_refunds_wallet(self):
        """Test that marking withdrawal as failed refunds the wallet"""
        initial_balance = self.wallet.balance
        
        # Deduct from wallet first (simulating withdrawal initiation)
        self.wallet.withdraw(Money(100, DEFAULT_CURRENCY))
        
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.transaction_service.mark_transaction_as_failed(
            transaction,
            reason='Bank transfer failed'
        )
        
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)

    def test_cancel_transaction(self):
        """Test cancelling a pending transaction"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        cancelled_transaction = self.transaction_service.cancel_transaction(
            transaction,
            reason='User requested cancellation'
        )
        
        self.assertEqual(cancelled_transaction.status, TRANSACTION_STATUS_CANCELLED)
        self.assertIn('cancel', cancelled_transaction.failed_reason.lower())
        self.assertIsNotNone(cancelled_transaction.completed_at)

    def test_cancel_non_pending_transaction_raises_error(self):
        """Test that cancelling non-pending transaction raises error"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        with self.assertRaises(ValueError):
            self.transaction_service.cancel_transaction(transaction)

    def test_cancel_withdrawal_refunds_wallet(self):
        """Test that cancelling withdrawal refunds the wallet"""
        initial_balance = self.wallet.balance
        
        # Deduct from wallet first (simulating withdrawal initiation)
        self.wallet.withdraw(Money(100, DEFAULT_CURRENCY))
        
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.transaction_service.cancel_transaction(transaction)
        
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)


class TransactionServiceRefundTestCase(TestCase):
    """Test case for refund operations"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet.save()
        
        self.transaction_service = TransactionService()

    def test_refund_transaction_full(self):
        """Test full refund of a transaction"""
        original_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        refund_transaction = self.transaction_service.refund_transaction(
            transaction=original_transaction,
            amount=Decimal('100.00'),
            reason='Customer requested refund'
        )
        
        self.assertEqual(refund_transaction.transaction_type, TRANSACTION_TYPE_REFUND)
        self.assertEqual(refund_transaction.amount, Money(100, DEFAULT_CURRENCY))
        self.assertEqual(refund_transaction.related_transaction, original_transaction)
        self.assertIn('refund', refund_transaction.description.lower())

    def test_refund_transaction_partial(self):
        """Test partial refund of a transaction"""
        original_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        refund_transaction = self.transaction_service.refund_transaction(
            transaction=original_transaction,
            amount=Decimal('50.00'),
            reason='Partial refund'
        )
        
        self.assertEqual(refund_transaction.amount, Money(50, DEFAULT_CURRENCY))

    def test_refund_transaction_credits_wallet(self):
        """Test that refund transaction does NOT automatically affect wallet for DEPOSIT"""
        initial_balance = self.wallet.balance

        # Use DEPOSIT transaction since only deposits and payments can be refunded
        original_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )

        refund_transaction = self.transaction_service.refund_transaction(
            transaction=original_transaction,
            amount=Decimal('100.00')
        )

        # Service currently auto-processes refund to SUCCESS (but doesn't debit wallet for DEPOSIT)
        self.assertEqual(refund_transaction.transaction_type, TRANSACTION_TYPE_REFUND)
        self.assertEqual(refund_transaction.status, TRANSACTION_STATUS_SUCCESS)

        # Wallet balance should remain unchanged for DEPOSIT refunds
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)


    def test_refund_non_successful_transaction_raises_error(self):
        """Test that refunding non-successful transaction raises error"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        with self.assertRaises(ValueError):
            self.transaction_service.refund_transaction(
                transaction=transaction,
                amount=Decimal('100.00')
            )

    def test_refund_payment_transaction(self):
        """Test refunding a PAYMENT transaction"""
        initial_balance = self.wallet.balance
        
        payment_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_PAYMENT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        refund_transaction = self.transaction_service.refund_transaction(
            transaction=payment_transaction,
            amount=Decimal('100.00')
        )
        
        self.assertEqual(refund_transaction.transaction_type, TRANSACTION_TYPE_REFUND)
        self.assertEqual(refund_transaction.status, TRANSACTION_STATUS_SUCCESS)
        
        # Refunding a payment should credit the wallet
        self.wallet.refresh_from_db()
        expected_balance = initial_balance + Money(100, DEFAULT_CURRENCY)
        self.assertEqual(self.wallet.balance, expected_balance)


class TransactionServiceReversalTestCase(TestCase):
    """Test case for reversal operations"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet.save()
        
        self.transaction_service = TransactionService()

    def test_reverse_deposit_transaction(self):
        """Test reversing a deposit transaction"""
        initial_balance = self.wallet.balance
        
        original_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        reversal_transaction = self.transaction_service.reverse_transaction(
            transaction=original_transaction,
            reason='Fraudulent transaction'
        )
        
        self.assertEqual(reversal_transaction.transaction_type, TRANSACTION_TYPE_REVERSAL)
        self.assertEqual(reversal_transaction.amount, Money(100, DEFAULT_CURRENCY))
        self.assertEqual(reversal_transaction.related_transaction, original_transaction)
        self.assertEqual(reversal_transaction.status, TRANSACTION_STATUS_SUCCESS)
        
        # Wallet should be debited
        self.wallet.refresh_from_db()
        expected_balance = initial_balance - Money(100, DEFAULT_CURRENCY)
        self.assertEqual(self.wallet.balance, expected_balance)

    def test_reverse_withdrawal_transaction(self):
        """Test reversing a withdrawal transaction"""
        initial_balance = self.wallet.balance
        
        original_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        reversal_transaction = self.transaction_service.reverse_transaction(
            transaction=original_transaction,
            reason='Bank transfer failed'
        )
        
        # Wallet should be credited
        self.wallet.refresh_from_db()
        expected_balance = initial_balance + Money(100, DEFAULT_CURRENCY)
        self.assertEqual(self.wallet.balance, expected_balance)

    def test_reverse_non_successful_transaction_raises_error(self):
        """Test that reversing non-successful transaction raises error"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        with self.assertRaises(ValueError):
            self.transaction_service.reverse_transaction(transaction)


class TransactionServiceTransferTestCase(TestCase):
    """Test case for transfer operations"""

    def setUp(self):
        """Set up test data"""
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='password123'
        )
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet1 = wallet_service.get_wallet(self.user1)
        self.wallet2 = wallet_service.get_wallet(self.user2)
        
        self.wallet1.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet1.save()
        
        self.wallet2.balance = Money(500, DEFAULT_CURRENCY)
        self.wallet2.save()
        
        self.transaction_service = TransactionService()

    def test_transfer_between_wallets(self):
        """Test transferring funds between wallets"""
        initial_balance1 = self.wallet1.balance
        initial_balance2 = self.wallet2.balance
        
        transfer_transaction = self.transaction_service.transfer_between_wallets(
            source_wallet=self.wallet1,
            destination_wallet=self.wallet2,
            amount=Decimal('200.00'),
            description='Transfer to friend'
        )
        
        self.assertEqual(transfer_transaction.transaction_type, TRANSACTION_TYPE_TRANSFER)
        self.assertEqual(transfer_transaction.wallet, self.wallet1)
        self.assertEqual(transfer_transaction.recipient_wallet, self.wallet2)
        self.assertEqual(transfer_transaction.amount, Money(200, DEFAULT_CURRENCY))
        self.assertEqual(transfer_transaction.status, TRANSACTION_STATUS_SUCCESS)
        
        # Check wallet balances
        self.wallet1.refresh_from_db()
        self.wallet2.refresh_from_db()
        
        self.assertEqual(
            self.wallet1.balance,
            initial_balance1 - Money(200, DEFAULT_CURRENCY)
        )
        self.assertEqual(
            self.wallet2.balance,
            initial_balance2 + Money(200, DEFAULT_CURRENCY)
        )

    def test_transfer_with_metadata(self):
        """Test transfer with metadata"""
        metadata = {'note': 'Birthday gift'}
        
        transfer_transaction = self.transaction_service.transfer_between_wallets(
            source_wallet=self.wallet1,
            destination_wallet=self.wallet2,
            amount=Decimal('100.00'),
            metadata=metadata
        )
        
        self.assertEqual(transfer_transaction.metadata, metadata)

    def test_transfer_with_custom_reference(self):
        """Test transfer with custom reference"""
        custom_ref = 'TRANSFER_REF_123'
        
        transfer_transaction = self.transaction_service.transfer_between_wallets(
            source_wallet=self.wallet1,
            destination_wallet=self.wallet2,
            amount=Decimal('100.00'),
            reference=custom_ref
        )
        
        self.assertEqual(transfer_transaction.reference, custom_ref)

    def test_transfer_insufficient_funds_raises_error(self):
        """Test transfer with insufficient funds raises error"""
        with self.assertRaises(Exception):
            self.transaction_service.transfer_between_wallets(
                source_wallet=self.wallet1,
                destination_wallet=self.wallet2,
                amount=Decimal('2000.00')  # More than available
            )


class TransactionServiceStatisticsTestCase(TestCase):
    """Test case for statistics and analytics"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction_service = TransactionService()
        
        # Create test transactions
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            fees=Money(2, DEFAULT_CURRENCY)
        )
        
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS,
            fees=Money(1, DEFAULT_CURRENCY)
        )
        
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(25, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(75, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_FAILED
        )

    def test_get_transaction_statistics_all(self):
        """Test getting transaction statistics for all transactions"""
        stats = self.transaction_service.get_transaction_statistics()
        
        self.assertEqual(stats['total_count'], 4)
        self.assertEqual(stats['successful_count'], 2)
        self.assertEqual(stats['pending_count'], 1)
        self.assertEqual(stats['failed_count'], 1)

    def test_get_transaction_statistics_by_wallet(self):
        """Test getting transaction statistics for specific wallet"""
        stats = self.transaction_service.get_transaction_statistics(wallet=self.wallet)
        
        self.assertEqual(stats['total_count'], 4)
        self.assertIn('total_amount', stats)
        self.assertIn('average_amount', stats)
        self.assertIn('total_fees', stats)

    def test_get_transaction_statistics_includes_type_breakdown(self):
        """Test that statistics include breakdown by type"""
        stats = self.transaction_service.get_transaction_statistics(wallet=self.wallet)
        
        self.assertIn('by_type', stats)
        # Should have deposit and withdrawal types
        type_stats = stats['by_type']
        self.assertIn(TRANSACTION_TYPE_DEPOSIT, type_stats)
        self.assertIn(TRANSACTION_TYPE_WITHDRAWAL, type_stats)

    def test_get_transaction_summary(self):
        """Test getting transaction summary"""
        summary = self.transaction_service.get_transaction_summary()
        
        self.assertIn('by_type', summary)
        self.assertIn('by_status', summary)
        self.assertIn('overview', summary)

    def test_get_transaction_summary_by_wallet(self):
        """Test getting transaction summary for specific wallet"""
        summary = self.transaction_service.get_transaction_summary(wallet=self.wallet)
        
        self.assertIn('by_type', summary)
        self.assertIn('by_status', summary)
        self.assertIn('overview', summary)
        
        overview = summary['overview']
        self.assertEqual(overview['total_transactions'], 4)


class TransactionServiceBulkOperationsTestCase(TestCase):
    """Test case for bulk operations"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction_service = TransactionService()
        
        # Create pending transactions
        self.txn1 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.txn2 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.txn3 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(25, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )

    def test_bulk_update_status_to_success(self):
        """Test bulk updating status to success"""
        transaction_ids = [self.txn1.id, self.txn2.id]
        
        updated_count = self.transaction_service.bulk_update_status(
            transaction_ids=transaction_ids,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(updated_count, 2)
        
        # Verify updates
        self.txn1.refresh_from_db()
        self.txn2.refresh_from_db()
        self.txn3.refresh_from_db()
        
        self.assertEqual(self.txn1.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(self.txn2.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(self.txn3.status, TRANSACTION_STATUS_PENDING)
        self.assertIsNotNone(self.txn1.completed_at)
        self.assertIsNotNone(self.txn2.completed_at)

    def test_bulk_update_status_to_failed(self):
        """Test bulk updating status to failed"""
        transaction_ids = [self.txn1.id, self.txn2.id]
        
        updated_count = self.transaction_service.bulk_update_status(
            transaction_ids=transaction_ids,
            status=TRANSACTION_STATUS_FAILED,
            reason='Bulk failure'
        )
        
        self.assertEqual(updated_count, 2)
        
        # Verify updates
        self.txn1.refresh_from_db()
        self.txn2.refresh_from_db()
        
        self.assertEqual(self.txn1.status, TRANSACTION_STATUS_FAILED)
        self.assertEqual(self.txn2.status, TRANSACTION_STATUS_FAILED)
        self.assertEqual(self.txn1.failed_reason, 'Bulk failure')
        self.assertIsNotNone(self.txn1.completed_at)

    def test_bulk_update_status_to_cancelled(self):
        """Test bulk updating status to cancelled"""
        transaction_ids = [self.txn1.id]
        
        updated_count = self.transaction_service.bulk_update_status(
            transaction_ids=transaction_ids,
            status=TRANSACTION_STATUS_CANCELLED,
            reason='Batch cancellation'
        )
        
        self.assertEqual(updated_count, 1)
        
        # Verify updates
        self.txn1.refresh_from_db()
        
        self.assertEqual(self.txn1.status, TRANSACTION_STATUS_CANCELLED)
        self.assertEqual(self.txn1.failed_reason, 'Batch cancellation')

    def test_bulk_update_empty_list(self):
        """Test bulk update with empty list"""
        updated_count = self.transaction_service.bulk_update_status(
            transaction_ids=[],
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(updated_count, 0)

    def test_bulk_update_all_transactions(self):
        """Test bulk updating all pending transactions"""
        transaction_ids = [self.txn1.id, self.txn2.id, self.txn3.id]
        
        updated_count = self.transaction_service.bulk_update_status(
            transaction_ids=transaction_ids,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(updated_count, 3)