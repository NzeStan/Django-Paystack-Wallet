"""
Django Paystack Wallet - Transaction Serializer Tests
Comprehensive test coverage for all transaction serializers
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from djmoney.money import Money

from wallet.models import Transaction, Wallet, BankAccount, Bank
from wallet.serializers.transaction_serializer import (
    TransactionSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
    TransactionMinimalSerializer,
    TransactionCreateSerializer,
    TransactionVerifySerializer,
    TransactionRefundSerializer,
    TransactionCancelSerializer,
    TransactionFilterSerializer,
    TransactionStatisticsSerializer,
    TransactionSummarySerializer,
    TransactionExportSerializer,
)
from wallet.services.wallet_service import WalletService
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_FAILED,
    PAYMENT_METHOD_CARD,
    PAYMENT_METHOD_BANK_TRANSFER,
)


User = get_user_model()
DEFAULT_CURRENCY = get_wallet_setting('CURRENCY')


class TransactionSerializerTestCase(TestCase):
    """Test case for TransactionSerializer (full serializer)"""

    def setUp(self):
        """Set up test data"""
        # Create users
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='user1@example.com',
            password='password123'
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='user2@example.com',
            password='password123'
        )
        
        # Create wallets
        wallet_service = WalletService()
        self.wallet1 = wallet_service.get_wallet(self.user1)
        self.wallet1.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet1.save()
        
        self.wallet2 = wallet_service.get_wallet(self.user2)
        
        # Create a successful transaction
        self.transaction = Transaction.objects.create(
            wallet=self.wallet1,
            amount=Money(100, DEFAULT_CURRENCY),
            fees=Money(2.50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-001',
            description='Test deposit',
            payment_method=PAYMENT_METHOD_CARD,
            metadata={'source': 'test'},
            ip_address='127.0.0.1',
            user_agent='Test Agent'
        )
        
        # Create a transfer transaction
        self.transfer_transaction = Transaction.objects.create(
            wallet=self.wallet1,
            recipient_wallet=self.wallet2,
            amount=Money(50, DEFAULT_CURRENCY),
            fees=Money(0, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-002',
            description='Test transfer'
        )

    def test_transaction_serializer_includes_all_fields(self):
        """Test that TransactionSerializer includes all expected fields"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        # Basic fields
        self.assertIn('id', data)
        self.assertIn('reference', data)
        self.assertIn('description', data)
        self.assertIn('metadata', data)
        
        # Wallet fields
        self.assertIn('wallet_id', data)
        self.assertIn('wallet_tag', data)
        self.assertIn('wallet_user_email', data)
        
        # Amount fields
        self.assertIn('amount_value', data)
        self.assertIn('amount_currency', data)
        
        # Type and status fields
        self.assertIn('transaction_type', data)
        self.assertIn('transaction_type_display', data)
        self.assertIn('status', data)
        self.assertIn('status_display', data)
        self.assertIn('payment_method', data)
        self.assertIn('payment_method_display', data)
        
        # Relationship fields
        self.assertIn('recipient_wallet_id', data)
        self.assertIn('recipient_wallet_tag', data)
        self.assertIn('recipient_bank_account_id', data)
        self.assertIn('card_id', data)
        self.assertIn('related_transaction_id', data)
        
        # Fee and computed fields
        self.assertIn('fees_value', data)
        self.assertIn('net_amount', data)
        self.assertIn('is_successful', data)
        self.assertIn('is_failed', data)
        self.assertIn('is_pending', data)
        
        # Request metadata
        self.assertIn('ip_address', data)
        self.assertIn('user_agent', data)
        
        # Timestamps
        self.assertIn('created_at', data)
        self.assertIn('updated_at', data)
        self.assertIn('completed_at', data)
        self.assertIn('failed_reason', data)

    def test_transaction_serializer_wallet_fields(self):
        """Test wallet-related fields are correctly serialized"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(str(data['wallet_id']), str(self.wallet1.id))
        self.assertEqual(data['wallet_tag'], self.wallet1.tag)
        self.assertEqual(data['wallet_user_email'], self.user1.email)

    def test_transaction_serializer_amount_fields(self):
        """Test amount fields are correctly serialized"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(Decimal(data['amount_value']), Decimal('100.00'))
        self.assertEqual(data['amount_currency'], DEFAULT_CURRENCY)
        self.assertEqual(Decimal(data['fees_value']), Decimal('2.50'))
        self.assertEqual(Decimal(data['net_amount']), Decimal('97.50'))

    def test_transaction_serializer_display_fields(self):
        """Test display fields show human-readable values"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(data['transaction_type'], TRANSACTION_TYPE_DEPOSIT)
        self.assertIsNotNone(data['transaction_type_display'])
        self.assertEqual(data['status'], TRANSACTION_STATUS_SUCCESS)
        self.assertIsNotNone(data['status_display'])
        self.assertEqual(data['payment_method'], PAYMENT_METHOD_CARD)
        self.assertIsNotNone(data['payment_method_display'])

    def test_transaction_serializer_computed_fields(self):
        """Test computed boolean fields"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertTrue(data['is_successful'])
        self.assertFalse(data['is_failed'])
        self.assertFalse(data['is_pending'])

    def test_transaction_serializer_transfer_fields(self):
        """Test transfer-specific fields are correctly serialized"""
        serializer = TransactionSerializer(instance=self.transfer_transaction)
        data = serializer.data
        
        self.assertEqual(str(data['recipient_wallet_id']), str(self.wallet2.id))
        self.assertEqual(data['recipient_wallet_tag'], self.wallet2.tag)

    def test_transaction_serializer_null_fields(self):
        """Test that nullable fields handle None correctly"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        # Non-transfer transaction should have null recipient_wallet
        self.assertIsNone(data['recipient_wallet_id'])
        self.assertIsNone(data['recipient_wallet_tag'])
        self.assertIsNone(data['recipient_bank_account_id'])
        self.assertIsNone(data['card_id'])

    def test_transaction_serializer_metadata(self):
        """Test metadata field is correctly serialized"""
        serializer = TransactionSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertIsInstance(data['metadata'], dict)
        self.assertEqual(data['metadata']['source'], 'test')

    def test_transaction_serializer_read_only(self):
        """Test that all fields are read-only"""
        # Attempt to update via serializer
        serializer = TransactionSerializer(
            instance=self.transaction,
            data={
                'amount_value': '500.00',
                'status': TRANSACTION_STATUS_FAILED
            },
            partial=True
        )
        
        # Should be valid but not change anything
        self.assertTrue(serializer.is_valid())
        serializer.save()
        
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount.amount, Decimal('100.00'))
        self.assertEqual(self.transaction.status, TRANSACTION_STATUS_SUCCESS)


class TransactionDetailSerializerTestCase(TestCase):
    """Test case for TransactionDetailSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create bank
        self.bank = Bank.objects.create(
            name='Test Bank',
            code='TBK',
            country='NG'
        )
        
        # Create bank account
        self.bank_account = BankAccount.objects.create(
            wallet=self.wallet,
            account_name='Test Account',
            account_number='1234567890',
            bank=self.bank
        )
        
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-003',
            recipient_bank_account=self.bank_account,
            paystack_reference='PSK_test123',
            paystack_response={'status': 'success'}
        )

    def test_transaction_detail_serializer_includes_base_fields(self):
        """Test that TransactionDetailSerializer includes all base fields"""
        serializer = TransactionDetailSerializer(instance=self.transaction)
        data = serializer.data
        
        # Should have all TransactionSerializer fields
        self.assertIn('id', data)
        self.assertIn('reference', data)
        self.assertIn('amount_value', data)
        self.assertIn('wallet_id', data)

    def test_transaction_detail_serializer_paystack_fields(self):
        """Test Paystack-specific fields in detail serializer"""
        serializer = TransactionDetailSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertIn('paystack_reference', data)
        self.assertIn('paystack_response', data)
        self.assertEqual(data['paystack_reference'], 'PSK_test123')
        self.assertIsInstance(data['paystack_response'], dict)

    def test_transaction_detail_recipient_wallet_details(self):
        """Test recipient_wallet_details method field"""
        user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='password123'
        )
        wallet_service = WalletService()
        wallet2 = wallet_service.get_wallet(user2)
        
        transfer = Transaction.objects.create(
            wallet=self.wallet,
            recipient_wallet=wallet2,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-004'
        )
        
        serializer = TransactionDetailSerializer(instance=transfer)
        data = serializer.data
        
        self.assertIn('recipient_wallet_details', data)
        self.assertIsNotNone(data['recipient_wallet_details'])
        self.assertEqual(data['recipient_wallet_details']['id'], str(wallet2.id))
        self.assertEqual(data['recipient_wallet_details']['tag'], wallet2.tag)
        self.assertEqual(data['recipient_wallet_details']['user_email'], user2.email)

    def test_transaction_detail_recipient_bank_account_details(self):
        """Test recipient_bank_account_details method field"""
        serializer = TransactionDetailSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertIn('recipient_bank_account_details', data)
        self.assertIsNotNone(data['recipient_bank_account_details'])
        self.assertEqual(
            data['recipient_bank_account_details']['id'],
            str(self.bank_account.id)
        )
        self.assertEqual(
            data['recipient_bank_account_details']['account_name'],
            'Test Account'
        )
        self.assertEqual(
            data['recipient_bank_account_details']['account_number'],
            '1234567890'
        )
        self.assertEqual(
            data['recipient_bank_account_details']['bank_name'],
            'Test Bank'
        )

    def test_transaction_detail_null_recipient_details(self):
        """Test recipient details are None when not applicable"""
        transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-005'
        )
        
        serializer = TransactionDetailSerializer(instance=transaction)
        data = serializer.data
        
        self.assertIsNone(data['recipient_wallet_details'])
        self.assertIsNone(data['recipient_bank_account_details'])


class TransactionListSerializerTestCase(TestCase):
    """Test case for TransactionListSerializer (lightweight)"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-006',
            description='Test list transaction'
        )

    def test_transaction_list_serializer_includes_essential_fields(self):
        """Test that TransactionListSerializer includes only essential fields"""
        serializer = TransactionListSerializer(instance=self.transaction)
        data = serializer.data
        
        # Should have essential fields
        self.assertIn('id', data)
        self.assertIn('reference', data)
        self.assertIn('amount_value', data)
        self.assertIn('amount_currency', data)
        self.assertIn('transaction_type', data)
        self.assertIn('transaction_type_display', data)
        self.assertIn('status', data)
        self.assertIn('status_display', data)
        self.assertIn('description', data)
        self.assertIn('created_at', data)
        self.assertIn('completed_at', data)

    def test_transaction_list_serializer_excludes_verbose_fields(self):
        """Test that TransactionListSerializer excludes verbose fields"""
        serializer = TransactionListSerializer(instance=self.transaction)
        data = serializer.data
        
        # Should NOT have verbose fields
        self.assertNotIn('wallet_id', data)
        self.assertNotIn('wallet_tag', data)
        self.assertNotIn('metadata', data)
        self.assertNotIn('ip_address', data)
        self.assertNotIn('user_agent', data)
        self.assertNotIn('paystack_reference', data)

    def test_transaction_list_serializer_amount_format(self):
        """Test amount fields are correctly formatted"""
        serializer = TransactionListSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(Decimal(data['amount_value']), Decimal('100.00'))
        self.assertEqual(data['amount_currency'], DEFAULT_CURRENCY)


class TransactionMinimalSerializerTestCase(TestCase):
    """Test case for TransactionMinimalSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-007'
        )

    def test_transaction_minimal_serializer_has_minimal_fields(self):
        """Test TransactionMinimalSerializer has only minimal fields"""
        serializer = TransactionMinimalSerializer(instance=self.transaction)
        data = serializer.data
        
        # Should have exactly these fields
        expected_fields = {'id', 'reference', 'amount_value', 'transaction_type', 'status'}
        self.assertEqual(set(data.keys()), expected_fields)

    def test_transaction_minimal_serializer_values(self):
        """Test TransactionMinimalSerializer field values"""
        serializer = TransactionMinimalSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(str(data['id']), str(self.transaction.id))
        self.assertEqual(data['reference'], 'test-ref-007')
        self.assertEqual(Decimal(data['amount_value']), Decimal('100.00'))
        self.assertEqual(data['transaction_type'], TRANSACTION_TYPE_DEPOSIT)
        self.assertEqual(data['status'], TRANSACTION_STATUS_SUCCESS)


class TransactionCreateSerializerTestCase(TestCase):
    """Test case for TransactionCreateSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_transaction_create_serializer_valid_data(self):
        """Test creating a transaction with valid data"""
        data = {
            'wallet': self.wallet.id,
            'amount': '100.00',
            'transaction_type': TRANSACTION_TYPE_DEPOSIT,
            'description': 'Test deposit',
            'metadata': {'source': 'test'}
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['amount'], Decimal('100.00'))

    def test_transaction_create_serializer_amount_validation_positive(self):
        """Test amount must be positive"""
        data = {
            'wallet': self.wallet.id,
            'amount': '0',
            'transaction_type': TRANSACTION_TYPE_DEPOSIT
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_transaction_create_serializer_amount_validation_negative(self):
        """Test amount cannot be negative"""
        data = {
            'wallet': self.wallet.id,
            'amount': '-50.00',
            'transaction_type': TRANSACTION_TYPE_DEPOSIT
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_transaction_create_serializer_maximum_amount(self):
        """Test amount cannot exceed maximum limit"""
        # This assumes there's a maximum daily transaction limit set
        data = {
            'wallet': self.wallet.id,
            'amount': '99999999999.99',  # Extremely large amount
            'transaction_type': TRANSACTION_TYPE_DEPOSIT
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_transaction_create_serializer_transfer_requires_recipient(self):
        """Test transfer transactions require recipient_wallet"""
        data = {
            'wallet': self.wallet.id,
            'amount': '50.00',
            'transaction_type': TRANSACTION_TYPE_TRANSFER
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('recipient_wallet', serializer.errors)

    def test_transaction_create_serializer_transfer_valid(self):
        """Test valid transfer transaction"""
        user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='password123'
        )
        wallet_service = WalletService()
        wallet2 = wallet_service.get_wallet(user2)
        
        data = {
            'wallet': self.wallet.id,
            'amount': '50.00',
            'transaction_type': TRANSACTION_TYPE_TRANSFER,
            'recipient_wallet': wallet2.id
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_create_serializer_prevent_self_transfer(self):
        """Test cannot transfer to same wallet"""
        data = {
            'wallet': self.wallet.id,
            'amount': '50.00',
            'transaction_type': TRANSACTION_TYPE_TRANSFER,
            'recipient_wallet': self.wallet.id
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('recipient_wallet', serializer.errors)

    def test_transaction_create_serializer_withdrawal_requires_bank_account(self):
        """Test withdrawal transactions require recipient_bank_account"""
        data = {
            'wallet': self.wallet.id,
            'amount': '50.00',
            'transaction_type': TRANSACTION_TYPE_WITHDRAWAL
        }
        
        serializer = TransactionCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('recipient_bank_account', serializer.errors)


class TransactionVerifySerializerTestCase(TestCase):
    """Test case for TransactionVerifySerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            reference='verify-test-ref-001'
        )

    def test_transaction_verify_serializer_valid_reference(self):
        """Test verifying with valid reference"""
        data = {'reference': 'verify-test-ref-001'}
        
        serializer = TransactionVerifySerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['reference'], 'verify-test-ref-001')

    def test_transaction_verify_serializer_invalid_reference(self):
        """Test verifying with non-existent reference"""
        data = {'reference': 'non-existent-ref'}
        
        serializer = TransactionVerifySerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('reference', serializer.errors)

    def test_transaction_verify_serializer_missing_reference(self):
        """Test verification requires reference"""
        data = {}
        
        serializer = TransactionVerifySerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('reference', serializer.errors)


class TransactionRefundSerializerTestCase(TestCase):
    """Test case for TransactionRefundSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create refundable transaction (DEPOSIT or PAYMENT)
        self.refundable_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='refund-test-ref-001'
        )
        
        # Create non-refundable transaction (WITHDRAWAL)
        self.non_refundable_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='refund-test-ref-002'
        )

    def test_transaction_refund_serializer_valid_full_refund(self):
        """Test valid full refund request"""
        data = {
            'transaction_id': str(self.refundable_transaction.id),
            'reason': 'Customer requested refund'
        }
        
        serializer = TransactionRefundSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_refund_serializer_valid_partial_refund(self):
        """Test valid partial refund request"""
        data = {
            'transaction_id': str(self.refundable_transaction.id),
            'amount': '50.00',
            'reason': 'Partial refund requested'
        }
        
        serializer = TransactionRefundSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['amount'], Decimal('50.00'))

    def test_transaction_refund_serializer_amount_exceeds_original(self):
        """Test refund amount cannot exceed original transaction amount"""
        data = {
            'transaction_id': str(self.refundable_transaction.id),
            'amount': '150.00',  # More than original 100.00
            'reason': 'Test'
        }
        
        serializer = TransactionRefundSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_transaction_refund_serializer_non_refundable_transaction(self):
        """Test cannot refund non-refundable transaction"""
        data = {
            'transaction_id': str(self.non_refundable_transaction.id),
            'reason': 'Test refund'
        }
        
        serializer = TransactionRefundSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('transaction_id', serializer.errors)

    def test_transaction_refund_serializer_invalid_transaction_id(self):
        """Test refund with non-existent transaction"""
        import uuid
        data = {
            'transaction_id': str(uuid.uuid4()),
            'reason': 'Test'
        }
        
        serializer = TransactionRefundSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('transaction_id', serializer.errors)

    def test_transaction_refund_serializer_negative_amount(self):
        """Test refund amount must be positive"""
        data = {
            'transaction_id': str(self.refundable_transaction.id),
            'amount': '-10.00',
            'reason': 'Test'
        }
        
        serializer = TransactionRefundSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)


class TransactionCancelSerializerTestCase(TestCase):
    """Test case for TransactionCancelSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create pending transaction (can be cancelled)
        self.pending_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            reference='cancel-test-ref-001'
        )
        
        # Create completed transaction (cannot be cancelled)
        self.completed_transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='cancel-test-ref-002'
        )

    def test_transaction_cancel_serializer_valid_cancellation(self):
        """Test valid transaction cancellation"""
        data = {
            'transaction_id': str(self.pending_transaction.id),
            'reason': 'User requested cancellation'
        }
        
        serializer = TransactionCancelSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_cancel_serializer_cannot_cancel_completed(self):
        """Test cannot cancel completed transaction"""
        data = {
            'transaction_id': str(self.completed_transaction.id),
            'reason': 'Trying to cancel'
        }
        
        serializer = TransactionCancelSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('transaction_id', serializer.errors)

    def test_transaction_cancel_serializer_invalid_transaction_id(self):
        """Test cancellation with non-existent transaction"""
        import uuid
        data = {
            'transaction_id': str(uuid.uuid4()),
            'reason': 'Test'
        }
        
        serializer = TransactionCancelSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('transaction_id', serializer.errors)

    def test_transaction_cancel_serializer_optional_reason(self):
        """Test reason is optional"""
        data = {
            'transaction_id': str(self.pending_transaction.id)
        }
        
        serializer = TransactionCancelSerializer(data=data)
        self.assertTrue(serializer.is_valid())


class TransactionFilterSerializerTestCase(TestCase):
    """Test case for TransactionFilterSerializer"""

    def test_transaction_filter_serializer_all_filters(self):
        """Test all filter parameters"""
        data = {
            'transaction_type': TRANSACTION_TYPE_DEPOSIT,
            'status': TRANSACTION_STATUS_SUCCESS,
            'min_amount': '10.00',
            'max_amount': '1000.00',
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'search': 'test',
            'ordering': '-created_at'
        }
        
        serializer = TransactionFilterSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_filter_serializer_optional_fields(self):
        """Test all filter fields are optional"""
        data = {}
        
        serializer = TransactionFilterSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_filter_serializer_partial_filters(self):
        """Test partial filter parameters"""
        data = {
            'transaction_type': TRANSACTION_TYPE_DEPOSIT,
            'min_amount': '50.00'
        }
        
        serializer = TransactionFilterSerializer(data=data)
        self.assertTrue(serializer.is_valid())


class TransactionStatisticsSerializerTestCase(TestCase):
    """Test case for TransactionStatisticsSerializer"""

    def test_transaction_statistics_serializer_structure(self):
        """Test statistics serializer accepts proper data structure"""
        data = {
            'total_count': 100,
            'successful_count': 85,
            'pending_count': 10,
            'failed_count': 5,
            'total_amount': '10000.00',
            'average_amount': '100.00',
            'total_fees': '250.00',
            'by_type': {
                'DEPOSIT': 50,
                'PAYMENT': 30,
                'TRANSFER': 20
            }
        }
        
        serializer = TransactionStatisticsSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_statistics_serializer_read_only(self):
        """Test all statistics fields are read-only"""
        # Create a statistics object (dict) to serialize
        stats_data = {
            'total_count': 100,
            'successful_count': 85,
            'pending_count': 10,
            'failed_count': 5,
            'total_amount': Decimal('10000.00'),
            'average_amount': Decimal('100.00'),
            'total_fees': Decimal('250.00'),
            'by_type': {'DEPOSIT': 50, 'PAYMENT': 30}
        }
        
        # For read-only serializers, use the serializer to output data
        serializer = TransactionStatisticsSerializer(stats_data)
        output_data = serializer.data
        
        # Verify all fields are in the output
        self.assertEqual(output_data['total_count'], 100)
        self.assertEqual(Decimal(output_data['total_amount']), Decimal('10000.00'))
        self.assertEqual(output_data['successful_count'], 85)


class TransactionSummarySerializerTestCase(TestCase):
    """Test case for TransactionSummarySerializer"""

    def test_transaction_summary_serializer_structure(self):
        """Test summary serializer accepts proper data structure"""
        data = {
            'by_type': {
                'DEPOSIT': {'count': 50, 'amount': '5000.00'},
                'PAYMENT': {'count': 30, 'amount': '3000.00'}
            },
            'by_status': {
                'SUCCESS': {'count': 85, 'amount': '8500.00'},
                'PENDING': {'count': 10, 'amount': '1000.00'}
            },
            'overview': {
                'total_count': 100,
                'total_amount': '10000.00'
            }
        }
        
        serializer = TransactionSummarySerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transaction_summary_serializer_dict_fields(self):
        """Test summary uses dict fields correctly"""
        # Create summary data to serialize
        summary_data = {
            'by_type': {'DEPOSIT': {'count': 50, 'amount': '5000.00'}},
            'by_status': {'SUCCESS': {'count': 85, 'amount': '8500.00'}},
            'overview': {'total_count': 100, 'total_amount': '10000.00'}
        }
        
        # For read-only serializers, use the serializer to output data
        serializer = TransactionSummarySerializer(summary_data)
        output_data = serializer.data
        
        # Verify all dict fields are present and are dicts
        self.assertIsInstance(output_data['by_type'], dict)
        self.assertIsInstance(output_data['by_status'], dict)
        self.assertIsInstance(output_data['overview'], dict)


class TransactionExportSerializerTestCase(TestCase):
    """Test case for TransactionExportSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            fees=Money(2.50, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='export-test-ref-001',
            description='Test export transaction',
            failed_reason=''
        )

    def test_transaction_export_serializer_includes_export_fields(self):
        """Test export serializer includes all export-specific fields"""
        serializer = TransactionExportSerializer(instance=self.transaction)
        data = serializer.data
        
        # Core fields
        self.assertIn('id', data)
        self.assertIn('reference', data)
        
        # Flattened wallet fields
        self.assertIn('wallet_tag', data)
        self.assertIn('wallet_user_email', data)
        
        # Flattened amount fields
        self.assertIn('amount', data)
        self.assertIn('currency', data)
        self.assertIn('fees', data)
        
        # Type and status with names
        self.assertIn('transaction_type', data)
        self.assertIn('transaction_type_name', data)
        self.assertIn('status', data)
        self.assertIn('status_name', data)
        
        # Additional fields
        self.assertIn('description', data)
        self.assertIn('created_at', data)
        self.assertIn('completed_at', data)
        self.assertIn('failed_reason', data)

    def test_transaction_export_serializer_flattened_values(self):
        """Test export serializer provides flattened values"""
        serializer = TransactionExportSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(data['wallet_tag'], self.wallet.tag)
        self.assertEqual(data['wallet_user_email'], self.user.email)
        self.assertEqual(Decimal(data['amount']), Decimal('100.00'))
        self.assertEqual(data['currency'], DEFAULT_CURRENCY)
        self.assertEqual(Decimal(data['fees']), Decimal('2.50'))

    def test_transaction_export_serializer_display_names(self):
        """Test export serializer includes human-readable names"""
        serializer = TransactionExportSerializer(instance=self.transaction)
        data = serializer.data
        
        self.assertEqual(data['transaction_type'], TRANSACTION_TYPE_DEPOSIT)
        self.assertIsNotNone(data['transaction_type_name'])
        self.assertEqual(data['status'], TRANSACTION_STATUS_SUCCESS)
        self.assertIsNotNone(data['status_name'])

    def test_transaction_export_serializer_read_only(self):
        """Test all export fields are read-only"""
        # Attempt to update via serializer
        serializer = TransactionExportSerializer(
            instance=self.transaction,
            data={'amount': '500.00'},
            partial=True
        )
        
        # Should be valid but not change anything
        self.assertTrue(serializer.is_valid())
        serializer.save()
        
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount.amount, Decimal('100.00'))


class TransactionSerializerListTestCase(TestCase):
    """Test case for serializing multiple transactions"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create multiple transactions
        self.transactions = [
            Transaction.objects.create(
                wallet=self.wallet,
                amount=Money(100 + i * 10, DEFAULT_CURRENCY),
                transaction_type=TRANSACTION_TYPE_DEPOSIT,
                status=TRANSACTION_STATUS_SUCCESS,
                reference=f'list-test-ref-{i:03d}'
            )
            for i in range(5)
        ]

    def test_serialize_multiple_transactions(self):
        """Test serializing a list of transactions"""
        serializer = TransactionListSerializer(self.transactions, many=True)
        data = serializer.data
        
        self.assertEqual(len(data), 5)
        self.assertTrue(all(isinstance(item, dict) for item in data))

    def test_serialize_queryset(self):
        """Test serializing a queryset"""
        queryset = Transaction.objects.filter(wallet=self.wallet)
        serializer = TransactionListSerializer(queryset, many=True)
        data = serializer.data
        
        self.assertEqual(len(data), 5)

    def test_serialize_empty_list(self):
        """Test serializing empty list"""
        serializer = TransactionListSerializer([], many=True)
        data = serializer.data
        
        self.assertEqual(len(data), 0)
        self.assertEqual(data, [])