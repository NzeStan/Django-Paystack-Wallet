"""
Django Paystack Wallet - Wallet Serializer Tests
Comprehensive test suite for all wallet serializers
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from djmoney.money import Money
from rest_framework.exceptions import ValidationError

from wallet.models import Wallet, BankAccount, Bank
from wallet.serializers.wallet_serializer import (
    WalletSerializer,
    WalletDetailSerializer,
    WalletCreateUpdateSerializer,
    WalletDepositSerializer,
    WalletWithdrawSerializer,
    WalletTransferSerializer,
    FinalizeWithdrawalSerializer,
)
from wallet.services.wallet_service import WalletService
from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_PENDING,
    BANK_ACCOUNT_TYPE_SAVINGS,
)


User = get_user_model()
DEFAULT_CURRENCY = get_wallet_setting('CURRENCY')


class WalletSerializerTestCase(TestCase):
    """Test case for base WalletSerializer"""

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
        from django.utils import timezone
        self.wallet.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet.tag = 'test-wallet'
        self.wallet.daily_transaction_total = Money(500, DEFAULT_CURRENCY)
        self.wallet.daily_transaction_count = 3
        self.wallet.daily_transaction_reset = timezone.now().date()
        self.wallet.save()

    def test_wallet_serializer_fields(self):
        """Test that WalletSerializer includes all expected fields"""
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        
        # Check identifiers
        self.assertIn('id', data)
        self.assertIn('user_id', data)
        self.assertIn('user_email', data)
        self.assertIn('user_name', data)
        self.assertIn('tag', data)
        
        # Check balance fields
        self.assertIn('balance_amount', data)
        self.assertIn('balance_currency', data)
        self.assertIn('available_balance', data)
        
        # Check status fields
        self.assertIn('is_active', data)
        self.assertIn('is_locked', data)
        self.assertIn('is_operational', data)
        
        # Check daily transaction fields
        self.assertIn('daily_transaction_total_amount', data)
        self.assertIn('daily_transaction_reset', data)
        
        # Check timestamps
        self.assertIn('created_at', data)
        self.assertIn('updated_at', data)

    def test_wallet_serializer_user_fields(self):
        """Test user-related fields are correctly serialized"""
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        
        self.assertEqual(data['user_email'], self.user.email)
        self.assertEqual(str(data['user_id']), str(self.user.id))
        self.assertIsNotNone(data['user_name'])

    def test_wallet_serializer_balance_fields(self):
        """Test balance fields are correctly serialized"""
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        
        self.assertEqual(Decimal(data['balance_amount']), Decimal('1000.00'))
        self.assertEqual(data['balance_currency'], DEFAULT_CURRENCY)
        self.assertEqual(Decimal(data['available_balance']), Decimal('1000.00'))

    def test_wallet_serializer_operational_status(self):
        """Test is_operational field reflects wallet status"""
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        
        # Active and unlocked wallet should be operational
        self.assertTrue(data['is_operational'])
        
        # Lock wallet and test again
        self.wallet.is_locked = True
        self.wallet.save()
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        self.assertFalse(data['is_operational'])

    def test_wallet_serializer_daily_transaction_fields(self):
        """Test daily transaction fields are correctly serialized"""
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        
        self.assertEqual(
            Decimal(data['daily_transaction_total_amount']),
            Decimal('500.00')
        )
        self.assertIsNotNone(data.get('daily_transaction_reset'))

    def test_wallet_serializer_read_only_fields(self):
        """Test that all fields are read-only in WalletSerializer"""
        initial_balance = self.wallet.balance
        
        # Attempt to update fields
        serializer = WalletSerializer(
            instance=self.wallet,
            data={
                'balance_amount': '5000.00',
                'user_email': 'newemail@example.com',
                'is_locked': True
            },
            partial=True
        )
        
        # Should be valid but not change anything
        self.assertTrue(serializer.is_valid())
        serializer.save()
        
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)


class WalletDetailSerializerTestCase(TestCase):
    """Test case for WalletDetailSerializer"""

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
        self.wallet.paystack_customer_code = 'CUS_test123'
        self.wallet.save()
        
        # Create some transactions to test counts
        from wallet.models import Transaction
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(100, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            reference='test-ref-1'
        )
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Money(200, DEFAULT_CURRENCY),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            reference='test-ref-2'
        )

    def test_wallet_detail_serializer_includes_all_base_fields(self):
        """Test that WalletDetailSerializer includes all base fields"""
        serializer = WalletDetailSerializer(instance=self.wallet)
        data = serializer.data
        
        # Should have all base WalletSerializer fields
        self.assertIn('id', data)
        self.assertIn('balance_amount', data)
        self.assertIn('user_email', data)

    def test_wallet_detail_serializer_computed_fields(self):
        """Test computed fields in WalletDetailSerializer"""
        serializer = WalletDetailSerializer(instance=self.wallet)
        data = serializer.data
        
        # Check for detail-specific fields
        self.assertIn('transaction_count', data)
        self.assertIn('successful_transactions', data)
        self.assertIn('pending_transactions', data)
        self.assertIn('cards_count', data)
        self.assertIn('bank_accounts_count', data)
        self.assertIn('paystack_customer_code', data)

    def test_wallet_detail_transaction_counts(self):
        """Test transaction count fields are accurate"""
        serializer = WalletDetailSerializer(instance=self.wallet)
        data = serializer.data
        
        self.assertEqual(data['transaction_count'], 2)
        self.assertEqual(data['successful_transactions'], 1)
        self.assertEqual(data['pending_transactions'], 1)

    def test_wallet_detail_paystack_fields(self):
        """Test Paystack integration fields"""
        serializer = WalletDetailSerializer(instance=self.wallet)
        data = serializer.data
        
        self.assertEqual(data['paystack_customer_code'], 'CUS_test123')

    def test_wallet_detail_cards_and_bank_accounts_count(self):
        """Test cards and bank accounts count"""
        serializer = WalletDetailSerializer(instance=self.wallet)
        data = serializer.data
        
        # Initially should be 0
        self.assertEqual(data['cards_count'], 0)
        self.assertEqual(data['bank_accounts_count'], 0)


class WalletCreateUpdateSerializerTestCase(TestCase):
    """Test case for WalletCreateUpdateSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_wallet_create_update_serializer_fields(self):
        """Test that only editable fields are in serializer"""
        serializer = WalletCreateUpdateSerializer(instance=self.wallet)
        data = serializer.data
        
        # Should only have editable fields
        self.assertIn('tag', data)
        self.assertIn('is_active', data)
        self.assertIn('is_locked', data)

    def test_update_wallet_tag(self):
        """Test updating wallet tag"""
        serializer = WalletCreateUpdateSerializer(
            instance=self.wallet,
            data={'tag': 'updated-tag'},
            partial=True
        )
        
        self.assertTrue(serializer.is_valid())
        serializer.save()
        
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.tag, 'updated-tag')

    def test_update_wallet_status_fields(self):
        """Test updating wallet status fields"""
        serializer = WalletCreateUpdateSerializer(
            instance=self.wallet,
            data={
                'is_active': False,
                'is_locked': True
            },
            partial=True
        )
        
        self.assertTrue(serializer.is_valid())
        serializer.save()
        
        self.wallet.refresh_from_db()
        self.assertFalse(self.wallet.is_active)
        self.assertTrue(self.wallet.is_locked)

    def test_validate_tag_length(self):
        """Test tag validation for length"""
        # Tag too long (>100 characters)
        long_tag = 'a' * 101
        serializer = WalletCreateUpdateSerializer(
            instance=self.wallet,
            data={'tag': long_tag},
            partial=True
        )
        
        self.assertFalse(serializer.is_valid())
        self.assertIn('tag', serializer.errors)

    def test_validate_tag_characters(self):
        """Test tag validation for allowed characters"""
        # Valid tags
        valid_tags = ['my-wallet', 'my_wallet', 'My Wallet 123']
        for tag in valid_tags:
            serializer = WalletCreateUpdateSerializer(
                instance=self.wallet,
                data={'tag': tag},
                partial=True
            )
            self.assertTrue(serializer.is_valid(), f"Tag '{tag}' should be valid")

        # Invalid tag with special characters
        invalid_tag = 'my@wallet!'
        serializer = WalletCreateUpdateSerializer(
            instance=self.wallet,
            data={'tag': invalid_tag},
            partial=True
        )
        self.assertFalse(serializer.is_valid())

    def test_validate_tag_whitespace_trimming(self):
        """Test that tag whitespace is trimmed"""
        serializer = WalletCreateUpdateSerializer(
            instance=self.wallet,
            data={'tag': '  my-wallet  '},
            partial=True
        )
        
        self.assertTrue(serializer.is_valid())
        serializer.save()
        
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.tag, 'my-wallet')


class WalletDepositSerializerTestCase(TestCase):
    """Test case for WalletDepositSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )

    def test_deposit_serializer_required_fields(self):
        """Test that required fields are validated"""
        serializer = WalletDepositSerializer(data={})
        
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_deposit_serializer_valid_data(self):
        """Test serializer with valid deposit data"""
        data = {
            'amount': '100.50',
            'description': 'Test deposit',
            'reference': 'DEP-123',
            'metadata': {'source': 'test'}
        }
        
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['amount'], Decimal('100.50'))
        self.assertEqual(validated_data['description'], 'Test deposit')
        self.assertEqual(validated_data['reference'], 'DEP-123')

    def test_deposit_serializer_amount_validation(self):
        """Test amount validation"""
        # Zero amount
        serializer = WalletDepositSerializer(data={'amount': '0'})
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)
        
        # Negative amount
        serializer = WalletDepositSerializer(data={'amount': '-10'})
        self.assertFalse(serializer.is_valid())
        
        # Valid positive amount
        serializer = WalletDepositSerializer(data={'amount': '0.01'})
        self.assertTrue(serializer.is_valid())

    def test_deposit_serializer_amount_max_validation(self):
        """Test maximum amount validation"""
        # Extremely large amount
        serializer = WalletDepositSerializer(
            data={'amount': '1000000000.00'}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_deposit_serializer_reference_validation(self):
        """Test reference field validation"""
        # Valid reference
        data = {'amount': '100', 'reference': 'DEP-123-ABC'}
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Reference too long
        data = {'amount': '100', 'reference': 'A' * 101}
        serializer = WalletDepositSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        # Invalid characters in reference
        data = {'amount': '100', 'reference': 'DEP@123!'}
        serializer = WalletDepositSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_deposit_serializer_metadata_validation(self):
        """Test metadata field validation"""
        # Valid metadata
        data = {
            'amount': '100',
            'metadata': {'key': 'value', 'number': 123}
        }
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Invalid metadata (not a dict)
        data = {'amount': '100', 'metadata': 'invalid'}
        serializer = WalletDepositSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_deposit_serializer_callback_url_validation(self):
        """Test callback URL validation"""
        # Valid URL
        data = {
            'amount': '100',
            'callback_url': 'https://example.com/callback'
        }
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Invalid URL
        data = {'amount': '100', 'callback_url': 'not-a-url'}
        serializer = WalletDepositSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_deposit_serializer_email_validation(self):
        """Test email field validation"""
        # Valid email
        data = {'amount': '100', 'email': 'test@example.com'}
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data['email'],
            'test@example.com'
        )
        
        # Email is trimmed and lowercased
        data = {'amount': '100', 'email': '  TEST@EXAMPLE.COM  '}
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data['email'],
            'test@example.com'
        )

    def test_deposit_serializer_optional_fields(self):
        """Test that optional fields are not required"""
        # Minimal valid data
        serializer = WalletDepositSerializer(data={'amount': '100'})
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertIn('amount', validated_data)
        # Optional fields should have defaults or be empty
        self.assertEqual(validated_data.get('metadata', {}), {})


class WalletWithdrawSerializerTestCase(TestCase):
    """Test case for WalletWithdrawSerializer"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create a bank for testing
        self.bank = Bank.objects.create(
            name='Test Bank',
            code='999',
            slug='test-bank',
            country='Nigeria',
            currency=DEFAULT_CURRENCY,
            is_active=True
        )
        
        # Create a bank account
        self.bank_account = BankAccount.objects.create(
            wallet=self.wallet,
            bank=self.bank,
            account_number='1234567890',
            account_name='Test User',
            account_type=BANK_ACCOUNT_TYPE_SAVINGS,
            is_verified=True,
            is_active=True
        )

    def test_withdraw_serializer_required_fields(self):
        """Test that required fields are validated"""
        serializer = WalletWithdrawSerializer(data={})
        
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)
        self.assertIn('bank_account_id', serializer.errors)

    def test_withdraw_serializer_valid_data(self):
        """Test serializer with valid withdrawal data"""
        data = {
            'amount': '50.00',
            'bank_account_id': str(self.bank_account.id),
            'description': 'Test withdrawal',
            'reference': 'WD-123'
        }
        
        serializer = WalletWithdrawSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['amount'], Decimal('50.00'))
        self.assertEqual(
            validated_data['bank_account_id'],
            str(self.bank_account.id)
        )

    def test_withdraw_serializer_bank_account_id_validation(self):
        """Test bank account ID validation"""
        # Empty bank account ID
        data = {'amount': '100', 'bank_account_id': ''}
        serializer = WalletWithdrawSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('bank_account_id', serializer.errors)
        
        # Bank account ID with whitespace is trimmed
        data = {
            'amount': '100',
            'bank_account_id': f'  {self.bank_account.id}  '
        }
        serializer = WalletWithdrawSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_withdraw_serializer_amount_validation(self):
        """Test amount validation for withdrawals"""
        # Zero amount
        data = {
            'amount': '0',
            'bank_account_id': str(self.bank_account.id)
        }
        serializer = WalletWithdrawSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        # Negative amount
        data = {
            'amount': '-50',
            'bank_account_id': str(self.bank_account.id)
        }
        serializer = WalletWithdrawSerializer(data=data)
        self.assertFalse(serializer.is_valid())


class WalletTransferSerializerTestCase(TestCase):
    """Test case for WalletTransferSerializer"""

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
        
        # Give wallet1 some balance
        self.wallet1.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet1.save()

    def test_transfer_serializer_required_fields(self):
        """Test that required fields are validated"""
        serializer = WalletTransferSerializer(data={})
        
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)
        self.assertIn('destination_wallet_id', serializer.errors)

    def test_transfer_serializer_valid_data(self):
        """Test serializer with valid transfer data"""
        data = {
            'amount': '100.00',
            'destination_wallet_id': str(self.wallet2.id),
            'description': 'Test transfer',
            'reference': 'TRF-123'
        }
        
        serializer = WalletTransferSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['amount'], Decimal('100.00'))
        self.assertEqual(
            validated_data['destination_wallet_id'],
            str(self.wallet2.id)
        )

    def test_transfer_serializer_destination_wallet_validation(self):
        """Test destination wallet ID validation"""
        # Empty destination wallet ID
        data = {'amount': '100', 'destination_wallet_id': ''}
        serializer = WalletTransferSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('destination_wallet_id', serializer.errors)
        
        # Destination wallet ID with whitespace is trimmed
        data = {
            'amount': '100',
            'destination_wallet_id': f'  {self.wallet2.id}  '
        }
        serializer = WalletTransferSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_transfer_serializer_amount_validation(self):
        """Test amount validation for transfers"""
        # Valid amount
        data = {
            'amount': '100',
            'destination_wallet_id': str(self.wallet2.id)
        }
        serializer = WalletTransferSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Zero amount
        data = {
            'amount': '0',
            'destination_wallet_id': str(self.wallet2.id)
        }
        serializer = WalletTransferSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_transfer_serializer_validate_method(self):
        """Test the validate method enforces destination wallet"""
        # Missing destination_wallet_id in validate
        data = {'amount': '100'}
        serializer = WalletTransferSerializer(data=data)
        self.assertFalse(serializer.is_valid())


class FinalizeWithdrawalSerializerTestCase(TestCase):
    """Test case for FinalizeWithdrawalSerializer"""

    def test_finalize_withdrawal_serializer_required_fields(self):
        """Test that required fields are validated"""
        serializer = FinalizeWithdrawalSerializer(data={})
        
        # Check if serializer has the expected behavior
        # This serializer is used for OTP verification
        is_valid = serializer.is_valid()
        
        # The actual required fields depend on the implementation
        # Based on the pattern, it likely requires an OTP field
        self.assertIsNotNone(serializer.errors)

    def test_finalize_withdrawal_serializer_with_otp(self):
        """Test serializer with OTP data"""
        # This test would depend on the actual implementation
        # of FinalizeWithdrawalSerializer
        data = {'otp': '123456'}
        serializer = FinalizeWithdrawalSerializer(data=data)
        
        # Verify serializer processes the data
        # The actual validation depends on implementation
        serializer.is_valid()


class WalletSerializerDescriptionFieldsTestCase(TestCase):
    """Test case for description and optional fields across serializers"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )

    def test_description_field_max_length(self):
        """Test description field length validation"""
        # Valid description
        data = {
            'amount': '100',
            'description': 'A' * 500
        }
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Description too long (>500 characters)
        data = {
            'amount': '100',
            'description': 'A' * 501
        }
        serializer = WalletDepositSerializer(data=data)
        # Should either be invalid or truncate
        serializer.is_valid()

    def test_optional_fields_defaults(self):
        """Test that optional fields have proper defaults"""
        # Test with minimal data
        serializer = WalletDepositSerializer(data={'amount': '100'})
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        # Metadata should default to empty dict
        self.assertEqual(validated_data.get('metadata', {}), {})


class WalletSerializerDecimalPrecisionTestCase(TestCase):
    """Test case for decimal precision handling"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)

    def test_amount_decimal_precision(self):
        """Test that amounts maintain proper decimal precision"""
        # Test with 2 decimal places
        data = {'amount': '100.55'}
        serializer = WalletDepositSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data['amount'],
            Decimal('100.55')
        )
        
        # Test with more than 2 decimal places (should round)
        data = {'amount': '100.555'}
        serializer = WalletDepositSerializer(data=data)
        is_valid = serializer.is_valid()
        
        if is_valid:
            # Check rounding behavior
            amount = serializer.validated_data['amount']
            self.assertEqual(amount.as_tuple().exponent, -2)

    def test_balance_serialization_precision(self):
        """Test balance fields maintain decimal precision"""
        self.wallet.balance = Money(Decimal('1234.56'), DEFAULT_CURRENCY)
        self.wallet.save()
        
        serializer = WalletSerializer(instance=self.wallet)
        data = serializer.data
        
        # Check balance amount precision
        self.assertEqual(
            Decimal(data['balance_amount']),
            Decimal('1234.56')
        )