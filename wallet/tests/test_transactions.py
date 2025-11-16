"""
Django Paystack Wallet - Transaction Model Tests
Comprehensive test suite for Transaction model

Test Coverage:
1. TransactionModelTestCase - Core model functionality
2. TransactionPropertiesTestCase - Model properties (is_completed, is_successful, etc.)
3. TransactionQuerySetTestCase - Custom QuerySet methods
4. TransactionManagerTestCase - Manager methods
5. TransactionTimestampsTestCase - Timestamp auto-setting
6. TransactionMetadataTestCase - JSON fields (metadata, paystack_response)
7. TransactionRelationshipsTestCase - Foreign key relationships
8. TransactionOrderingTestCase - Default ordering behavior

Note: The Transaction model uses:
- Manager method: for_wallet() - exposed at Transaction.objects.for_wallet()
- QuerySet method: by_wallet() - available when chaining (e.g., Transaction.objects.all().by_wallet())
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from djmoney.money import Money

from wallet.models import Transaction, Wallet, BankAccount, Bank, Card
from wallet.services.wallet_service import WalletService
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_TYPE_REFUND,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_CANCELLED,
    PAYMENT_METHOD_CARD,
    PAYMENT_METHOD_BANK_TRANSFER,
)


User = get_user_model()
DEFAULT_CURRENCY = get_wallet_setting('CURRENCY')


class TransactionModelTestCase(TestCase):
    """Test case for Transaction model core functionality"""

    def setUp(self):
        """Set up test data"""
        # Create users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='password123'
        )
        
        # Create wallets using service
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet2 = wallet_service.get_wallet(self.user2)
        
        # Set initial balance
        self.wallet.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet.save()
        
        self.wallet2.balance = Money(500, DEFAULT_CURRENCY)
        self.wallet2.save()
        
        # Create a bank
        self.bank = Bank.objects.create(
            name='Test Bank',
            code='TBK',
            country='NG'
        )
        
        # Create bank account
        self.bank_account = BankAccount.objects.create(
            wallet=self.wallet,
            bank=self.bank,
            account_number='1234567890',
            account_name='Test User'
        )
        
        # Create a card
        self.card = Card.objects.create(
            wallet=self.wallet,
            paystack_authorization_code='AUTH_test123',
            card_type='visa',
            last_four='4242',
            expiry_month='12',
            expiry_year='2025'
        )

    def test_create_transaction_basic(self):
        """Test creating a basic transaction"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            description='Test deposit'
        )
        
        self.assertIsNotNone(transaction.id)
        self.assertEqual(transaction.wallet, self.wallet)
        self.assertEqual(transaction.amount, Money(100, DEFAULT_CURRENCY))
        self.assertEqual(transaction.transaction_type, TRANSACTION_TYPE_DEPOSIT)
        self.assertEqual(transaction.status, TRANSACTION_STATUS_PENDING)
        self.assertEqual(transaction.description, 'Test deposit')
        self.assertIsNotNone(transaction.reference)  # Auto-generated
        self.assertIsNotNone(transaction.created_at)
        self.assertIsNotNone(transaction.updated_at)

    def test_auto_generate_reference(self):
        """Test that reference is auto-generated if not provided"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        self.assertIsNotNone(transaction.reference)
        self.assertTrue(len(transaction.reference) > 0)

    def test_custom_reference(self):
        """Test creating transaction with custom reference"""
        custom_ref = 'CUSTOM_REF_12345'
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            reference=custom_ref
        )
        
        self.assertEqual(transaction.reference, custom_ref)

    def test_unique_reference_constraint(self):
        """Test that reference must be unique"""
        reference = 'UNIQUE_REF_12345'
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            reference=reference
        )
        
        # Try to create another transaction with same reference
        with self.assertRaises(Exception):  # IntegrityError
            Transaction.objects.create(
                wallet=self.wallet,
                amount=Money(200, DEFAULT_CURRENCY),
                transaction_type=TRANSACTION_TYPE_DEPOSIT,
                reference=reference
            )

    def test_transaction_with_all_fields(self):
        """Test creating transaction with all optional fields"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(250, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS,
            description='Complete transaction',
            payment_method=PAYMENT_METHOD_BANK_TRANSFER,
            paystack_reference='PYSTACK_REF_123',
            paystack_response={'status': 'success'},
            recipient_wallet=self.wallet2,
            recipient_bank_account=self.bank_account,
            card=self.card,
            fees=Money(5, DEFAULT_CURRENCY),
            completed_at=timezone.now(),
            metadata={'key': 'value'}
        )
        
        self.assertEqual(transaction.amount, Money(250, DEFAULT_CURRENCY))
        self.assertEqual(transaction.payment_method, PAYMENT_METHOD_BANK_TRANSFER)
        self.assertEqual(transaction.paystack_reference, 'PYSTACK_REF_123')
        self.assertEqual(transaction.recipient_wallet, self.wallet2)
        self.assertEqual(transaction.recipient_bank_account, self.bank_account)
        self.assertEqual(transaction.card, self.card)
        self.assertEqual(transaction.fees, Money(5, DEFAULT_CURRENCY))
        self.assertIsNotNone(transaction.completed_at)
        self.assertEqual(transaction.metadata, {'key': 'value'})

    def test_transaction_string_representation(self):
        """Test __str__ method"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        str_repr = str(transaction)
        self.assertIn('Deposit', str_repr)
        self.assertIn('100', str_repr)
        self.assertIn('Success', str_repr)

    def test_transaction_repr(self):
        """Test __repr__ method"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        repr_str = repr(transaction)
        self.assertIn('Transaction', repr_str)
        self.assertIn(str(transaction.id), repr_str)
        self.assertIn(str(transaction.wallet_id), repr_str)
        self.assertIn(transaction.transaction_type, repr_str)
        self.assertIn(transaction.status, repr_str)

    def test_related_transaction(self):
        """Test related transaction link"""
        original_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        related_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_REFUND,
            status=TRANSACTION_STATUS_SUCCESS,
            related_transaction=original_transaction
        )
        
        self.assertEqual(related_transaction.related_transaction, original_transaction)


class TransactionPropertiesTestCase(TestCase):
    """Test case for Transaction model properties"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_is_completed_property_success(self):
        """Test is_completed property for successful transaction"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertTrue(transaction.is_completed)

    def test_is_completed_property_failed(self):
        """Test is_completed property for failed transaction"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_FAILED
        )
        
        self.assertTrue(transaction.is_completed)

    def test_is_completed_property_pending(self):
        """Test is_completed property for pending transaction"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.assertFalse(transaction.is_completed)

    def test_is_successful_property(self):
        """Test is_successful property"""
        transaction_success = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        transaction_pending = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.assertTrue(transaction_success.is_successful)
        self.assertFalse(transaction_pending.is_successful)

    def test_is_failed_property(self):
        """Test is_failed property"""
        transaction_failed = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_FAILED,
            failed_reason='Payment declined'
        )
        
        transaction_success = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertTrue(transaction_failed.is_failed)
        self.assertFalse(transaction_success.is_failed)

    def test_is_pending_property(self):
        """Test is_pending property"""
        transaction_pending = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        transaction_success = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertTrue(transaction_pending.is_pending)
        self.assertFalse(transaction_success.is_pending)

    def test_is_cancelled_property(self):
        """Test is_cancelled property"""
        transaction_cancelled = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_CANCELLED
        )
        
        transaction_success = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertTrue(transaction_cancelled.is_cancelled)
        self.assertFalse(transaction_success.is_cancelled)

    def test_net_amount_property_no_fees(self):
        """Test net_amount property without fees"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(transaction.net_amount, Money(100, DEFAULT_CURRENCY))

    def test_net_amount_property_with_fees(self):
        """Test net_amount property with fees"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            fees=Money(5, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        expected_net = Money(100, DEFAULT_CURRENCY) - Money(5, DEFAULT_CURRENCY)
        self.assertEqual(transaction.net_amount, expected_net)


class TransactionQuerySetTestCase(TestCase):
    """Test case for Transaction QuerySet methods"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet2 = wallet_service.get_wallet(self.user2)
        
        # Create transactions with different statuses
        self.txn_success = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.txn_pending = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(200, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.txn_failed = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(150, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_FAILED
        )
        
        self.txn_cancelled = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(75, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_CANCELLED
        )
        
        # Create transaction for wallet2
        self.txn_wallet2 = Transaction.objects.create(
            wallet=self.wallet2,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )

    def test_successful_queryset(self):
        """Test successful() queryset method"""
        successful_txns = Transaction.objects.successful()
        
        self.assertEqual(successful_txns.count(), 2)
        self.assertIn(self.txn_success, successful_txns)
        self.assertIn(self.txn_wallet2, successful_txns)
        self.assertNotIn(self.txn_pending, successful_txns)
        self.assertNotIn(self.txn_failed, successful_txns)

    def test_pending_queryset(self):
        """Test pending() queryset method"""
        pending_txns = Transaction.objects.pending()
        
        self.assertEqual(pending_txns.count(), 1)
        self.assertIn(self.txn_pending, pending_txns)
        self.assertNotIn(self.txn_success, pending_txns)

    def test_failed_queryset(self):
        """Test failed() queryset method"""
        failed_txns = Transaction.objects.failed()
        
        self.assertEqual(failed_txns.count(), 1)
        self.assertIn(self.txn_failed, failed_txns)
        self.assertNotIn(self.txn_success, failed_txns)

    def test_cancelled_queryset(self):
        """Test cancelled() queryset method"""
        cancelled_txns = Transaction.objects.cancelled()
        
        self.assertEqual(cancelled_txns.count(), 1)
        self.assertIn(self.txn_cancelled, cancelled_txns)
        self.assertNotIn(self.txn_success, cancelled_txns)

    def test_by_type_queryset(self):
        """Test by_type() queryset method"""
        deposit_txns = Transaction.objects.by_type(TRANSACTION_TYPE_DEPOSIT)
        
        self.assertEqual(deposit_txns.count(), 3)  # txn_success, txn_failed, txn_wallet2
        self.assertIn(self.txn_success, deposit_txns)
        self.assertIn(self.txn_failed, deposit_txns)
        self.assertIn(self.txn_wallet2, deposit_txns)
        self.assertNotIn(self.txn_pending, deposit_txns)

    def test_by_wallet_queryset(self):
        """Test for_wallet() manager method (which uses by_wallet queryset internally)"""
        wallet1_txns = Transaction.objects.for_wallet(self.wallet)
        
        self.assertEqual(wallet1_txns.count(), 4)
        self.assertIn(self.txn_success, wallet1_txns)
        self.assertIn(self.txn_pending, wallet1_txns)
        self.assertIn(self.txn_failed, wallet1_txns)
        self.assertIn(self.txn_cancelled, wallet1_txns)
        self.assertNotIn(self.txn_wallet2, wallet1_txns)

    def test_by_wallet_on_queryset(self):
        """Test by_wallet() when called on a queryset (not manager)"""
        # by_wallet is available on queryset, not manager
        wallet1_txns = Transaction.objects.all().by_wallet(self.wallet)
        
        self.assertEqual(wallet1_txns.count(), 4)
        self.assertIn(self.txn_success, wallet1_txns)
        self.assertNotIn(self.txn_wallet2, wallet1_txns)

    def test_chain_queryset_methods(self):
        """Test chaining multiple queryset methods"""
        # Get successful deposits for wallet
        result = Transaction.objects.successful().by_type(TRANSACTION_TYPE_DEPOSIT).by_wallet(self.wallet)
        
        self.assertEqual(result.count(), 1)
        self.assertIn(self.txn_success, result)

    def test_for_wallet_manager_method(self):
        """Test for_wallet() manager method"""
        wallet1_txns = Transaction.objects.for_wallet(self.wallet)
        
        self.assertEqual(wallet1_txns.count(), 4)
        self.assertNotIn(self.txn_wallet2, wallet1_txns)


class TransactionManagerTestCase(TestCase):
    """Test case for Transaction Manager methods"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create some transactions
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING
        )

    def test_manager_returns_all_transactions(self):
        """Test that manager returns all transactions"""
        all_txns = Transaction.objects.all()
        self.assertEqual(all_txns.count(), 2)

    def test_manager_successful_method(self):
        """Test manager successful() method"""
        successful = Transaction.objects.successful()
        self.assertEqual(successful.count(), 1)

    def test_manager_pending_method(self):
        """Test manager pending() method"""
        pending = Transaction.objects.pending()
        self.assertEqual(pending.count(), 1)


class TransactionTimestampsTestCase(TestCase):
    """Test case for Transaction timestamps"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_created_at_auto_set(self):
        """Test that created_at is automatically set"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        self.assertIsNotNone(transaction.created_at)
        self.assertLessEqual(
            (timezone.now() - transaction.created_at).total_seconds(),
            2
        )

    def test_updated_at_auto_set(self):
        """Test that updated_at is automatically set"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        self.assertIsNotNone(transaction.updated_at)

    def test_completed_at_manual_set(self):
        """Test completed_at field"""
        completed_time = timezone.now()
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            completed_at=completed_time
        )
        
        self.assertEqual(transaction.completed_at, completed_time)

    def test_completed_at_null_for_pending(self):
        """Test that completed_at is null for pending transactions"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING
        )
        
        self.assertIsNone(transaction.completed_at)


class TransactionMetadataTestCase(TestCase):
    """Test case for Transaction metadata and JSON fields"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_metadata_field(self):
        """Test metadata JSON field"""
        metadata = {
            'customer_id': '12345',
            'order_id': 'ORD-001',
            'notes': 'Test transaction'
        }
        
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            metadata=metadata
        )
        
        self.assertEqual(transaction.metadata, metadata)
        self.assertEqual(transaction.metadata['customer_id'], '12345')

    def test_paystack_response_field(self):
        """Test paystack_response JSON field"""
        paystack_data = {
            'status': 'success',
            'reference': 'REF123',
            'amount': 10000,
            'channel': 'card'
        }
        
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            paystack_response=paystack_data
        )
        
        self.assertEqual(transaction.paystack_response, paystack_data)
        self.assertEqual(transaction.paystack_response['status'], 'success')

    def test_empty_metadata(self):
        """Test transaction with empty metadata"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        # Should be None or empty dict depending on field definition
        self.assertIn(transaction.metadata, [None, {}, dict()])


class TransactionRelationshipsTestCase(TestCase):
    """Test case for Transaction relationships"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet2 = wallet_service.get_wallet(self.user2)
        
        self.bank = Bank.objects.create(
            name='Test Bank',
            code='TBK',
            country='NG'
        )
        
        self.bank_account = BankAccount.objects.create(
            wallet=self.wallet,
            bank=self.bank,
            account_number='1234567890',
            account_name='Test User'
        )
        
        self.card = Card.objects.create(
            wallet=self.wallet,
            paystack_authorization_code='AUTH_test123',
            card_type='visa',
            last_four='4242',
            expiry_month='12',
            expiry_year='2025'
        )

    def test_wallet_relationship(self):
        """Test wallet foreign key relationship"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        self.assertEqual(transaction.wallet, self.wallet)
        self.assertIn(transaction, self.wallet.transactions.all())

    def test_recipient_wallet_relationship(self):
        """Test recipient_wallet foreign key"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            recipient_wallet=self.wallet2
        )
        
        self.assertEqual(transaction.recipient_wallet, self.wallet2)
        self.assertIn(transaction, self.wallet2.received_transactions.all())

    def test_recipient_bank_account_relationship(self):
        """Test recipient_bank_account foreign key"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            recipient_bank_account=self.bank_account
        )
        
        self.assertEqual(transaction.recipient_bank_account, self.bank_account)

    def test_card_relationship(self):
        """Test card foreign key"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            card=self.card
        )
        
        self.assertEqual(transaction.card, self.card)

    def test_cascade_delete_wallet(self):
        """Test that deleting wallet cascades to transactions"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        txn_id = transaction.id
        self.wallet.delete()
        
        # Transaction should be deleted
        with self.assertRaises(Transaction.DoesNotExist):
            Transaction.objects.get(id=txn_id)


class TransactionOrderingTestCase(TestCase):
    """Test case for Transaction ordering"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_default_ordering(self):
        """Test default ordering by created_at descending"""
        # Create transactions with slight time gaps
        import time
        
        txn1 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        time.sleep(0.1)
        
        txn2 = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(200, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        transactions = Transaction.objects.all()
        
        # Most recent should be first (descending order)
        self.assertEqual(transactions[0].id, txn2.id)
        self.assertEqual(transactions[1].id, txn1.id)