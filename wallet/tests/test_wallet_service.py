"""
Test cases for WalletService
Comprehensive tests with mocking for Paystack integrations
"""
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from djmoney.money import Money
import random
from wallet.models import (
    Wallet, Transaction, Card, BankAccount, 
    TransferRecipient, Bank
)
from wallet.services.wallet_service import WalletService
from wallet.exceptions import (
    TransactionFailed,
    InsufficientFunds,
    InvalidAmount,
    WalletLocked,
    BankAccountError,
    PaystackAPIError
)
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED
)


User = get_user_model()


class WalletServiceTestCase(TestCase):
    """Test case for WalletService"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create test users
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='testuser1@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User1'
        )
        
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='testuser2@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User2'
        )
        
        # Create test wallets
        self.wallet1 = Wallet.objects.create(
            user=self.user1,
            balance=Money(1000, 'NGN'),
            tag='TEST-WALLET-1',
            paystack_customer_code='CUS_test123'
        )
        
        self.wallet2 = Wallet.objects.create(
            user=self.user2,
            balance=Money(500, 'NGN'),
            tag='TEST-WALLET-2',
            paystack_customer_code='CUS_test456'
        )
        
        # Create test bank
        self.test_bank = Bank.objects.create(
            name='Test Bank',
            code='058',
            slug='test-bank',
            country='Nigeria'
        )
        
        # Create test bank account
        self.bank_account = BankAccount.objects.create(
            wallet=self.wallet1,
            bank=self.test_bank,
            account_number='1234567890',
            account_name='Test User One',
            account_type='savings',
            is_verified=True,
            paystack_recipient_code='RCP_test123'
        )
        
        # Create test card
        self.card = Card.objects.create(
            wallet=self.wallet1,
            email=self.user1.email,
            paystack_authorization_code='AUTH_test123',
            card_type='visa',
            last_four='4321',
            expiry_month='12',
            expiry_year='2025',
            bin='408408',
        )
        
        # Initialize service with mocked Paystack
        self.service = WalletService()
        self.mock_paystack = Mock()
        self.service.paystack = self.mock_paystack


class WalletManagementTests(WalletServiceTestCase):
    """Tests for wallet management operations"""
    
    def test_get_wallet_existing(self):
        """Test getting an existing wallet"""
        wallet = self.service.get_wallet(self.user1)
        
        self.assertEqual(wallet.id, self.wallet1.id)
        self.assertEqual(wallet.user, self.user1)
    
    @patch('wallet.services.wallet_service.generate_wallet_tag')
    def test_get_wallet_creates_new(self, mock_generate_tag):
        """Test creating a new wallet for user without one"""
        mock_generate_tag.return_value = 'NEW-WALLET-TAG'
        self.mock_paystack.create_customer.return_value = {
            'customer_code': 'CUS_new123'
        }
        self.mock_paystack.create_dedicated_account.return_value = {
            'account_number': '9876543210',
            'bank': {'name': 'Wema Bank'}
        }
        
        # Create new user without wallet
        new_user = User.objects.create_user(
            username='newuser',
            email='newuser@example.com',
            password='testpass123'
        )
        
        wallet = self.service.get_wallet(new_user)
        
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.user, new_user)
        self.assertEqual(wallet.tag, 'NEW-WALLET-TAG')
        mock_generate_tag.assert_called_once_with(new_user)
    
    def test_setup_paystack_customer_success(self):
        """Test successful Paystack customer setup"""
        self.mock_paystack.create_customer.return_value = {
            'customer_code': 'CUS_xyz789'
        }
        self.mock_paystack.create_dedicated_account.return_value = {
            'account_number': '1122334455',
            'bank': {'name': 'GTBank'}
        }
        
        # Create wallet without customer code
        Wallet.objects.filter(user=self.user1).delete()
        wallet = Wallet.objects.create(user=self.user1)
        
        self.service._setup_paystack_customer(wallet)
        
        wallet.refresh_from_db()
        self.assertEqual(wallet.paystack_customer_code, 'CUS_xyz789')
        self.mock_paystack.create_customer.assert_called_once()
    
    def test_setup_paystack_customer_failure(self):
        """Test Paystack customer setup handles failures gracefully"""
        self.mock_paystack.create_customer.side_effect = Exception("API Error")
        
        Wallet.objects.filter(user=self.user1).delete()
        wallet = Wallet.objects.create(user=self.user1)
        
        # Should not raise exception
        self.service._setup_paystack_customer(wallet)
        
        wallet.refresh_from_db()
        self.assertIsNone(wallet.paystack_customer_code)
    
    def test_create_dedicated_account_success(self):
        """Test creating dedicated virtual account"""
        self.mock_paystack.create_dedicated_account.return_value = {
            'account_number': '5566778899',
            'bank': {'name': 'Access Bank'}
        }
        
        result = self.service.create_dedicated_account(self.wallet1)
        
        self.assertTrue(result)
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.dedicated_account_number, '5566778899')
        self.assertEqual(self.wallet1.dedicated_account_bank, 'Access Bank')
    
    def test_create_dedicated_account_no_customer_code(self):
        """Test dedicated account creation fails without customer code"""
        
        Wallet.objects.filter(user=self.user1).delete()
        wallet = Wallet.objects.create(user=self.user1)
        
        result = self.service.create_dedicated_account(wallet)
        
        self.assertFalse(result)
        self.mock_paystack.create_dedicated_account.assert_not_called()
    
    def test_get_balance(self):
        """Test getting wallet balance"""
        balance = self.service.get_balance(self.wallet1)
        
        self.assertEqual(balance.amount, Decimal('1000'))
        self.assertEqual(str(balance.currency), 'NGN')


class DepositOperationsTests(WalletServiceTestCase):
    """Tests for deposit operations"""
    
    @patch('wallet.services.wallet_service.generate_transaction_reference')
    def test_deposit_success(self, mock_generate_ref):
        """Test successful deposit"""
        mock_generate_ref.return_value = 'TXN_deposit123'
        initial_balance = self.wallet1.balance.amount
        deposit_amount = Decimal('500')
        
        transaction = self.service.deposit(
            wallet=self.wallet1,
            amount=deposit_amount,
            description='Test deposit'
        )
        
        self.assertEqual(transaction.transaction_type, TRANSACTION_TYPE_DEPOSIT)
        self.assertEqual(transaction.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(transaction.amount.amount, deposit_amount)
        self.assertIsNotNone(transaction.completed_at)
        
        # Verify balance increased
        self.wallet1.refresh_from_db()
        self.assertEqual(
            self.wallet1.balance.amount,
            initial_balance + deposit_amount
        )
    
    def test_deposit_with_metadata(self):
        """Test deposit with custom metadata"""
        metadata = {'source': 'test', 'user_id': '123'}
        
        transaction = self.service.deposit(
            wallet=self.wallet1,
            amount=Decimal('100'),
            metadata=metadata
        )
        
        self.assertEqual(transaction.metadata, metadata)
    
    def test_deposit_with_custom_reference(self):
        """Test deposit with custom reference"""
        custom_ref = 'CUSTOM_REF_123'
        
        transaction = self.service.deposit(
            wallet=self.wallet1,
            amount=Decimal('100'),
            transaction_reference=custom_ref
        )
        
        self.assertEqual(transaction.reference, custom_ref)
    
    def test_deposit_failure_wallet_locked(self):
        """Test deposit fails when wallet is locked"""
        self.wallet1.is_active = False
        self.wallet1.save()
        
        with self.assertRaises(WalletLocked):
            self.service.deposit(
                wallet=self.wallet1,
                amount=Decimal('100')
            )
    
    @patch('wallet.services.wallet_service.generate_transaction_reference')
    def test_initialize_card_charge(self, mock_generate_ref):
        """Test initializing card charge"""
        mock_generate_ref.return_value = 'TXN_charge123'
        self.mock_paystack.initialize_transaction.return_value = {
            'authorization_url': 'https://checkout.paystack.com/xyz',
            'access_code': 'access123',
            'reference': 'TXN_charge123'
        }
        
        charge_data = self.service.initialize_card_charge(
            wallet=self.wallet1,
            amount=Decimal('5000'),
            callback_url='https://example.com/callback'
        )
        
        self.assertEqual(charge_data['reference'], 'TXN_charge123')
        self.assertIn('authorization_url', charge_data)
        
        # Verify Paystack was called with correct parameters
        self.mock_paystack.initialize_transaction.assert_called_once()
        call_kwargs = self.mock_paystack.initialize_transaction.call_args[1]
        self.assertEqual(call_kwargs['amount'], 500000)  # In kobo
        self.assertEqual(call_kwargs['email'], self.user1.email)
    
    def test_initialize_card_charge_no_email(self):
        """Test card charge fails without email"""
        user_without_email = User.objects.create_user(
            username='noemail',
            password='test123'
        )
        wallet = Wallet.objects.create(user=user_without_email)
        
        with self.assertRaises(ValueError):
            self.service.initialize_card_charge(
                wallet=wallet,
                amount=Decimal('1000')
            )


class WithdrawalOperationsTests(WalletServiceTestCase):
    """Tests for withdrawal operations"""
    
    @patch('wallet.services.wallet_service.generate_transaction_reference')
    def test_withdraw_success(self, mock_generate_ref):
        """Test successful withdrawal"""
        mock_generate_ref.return_value = 'TXN_withdraw123'
        initial_balance = self.wallet1.balance.amount
        withdraw_amount = Decimal('300')
        
        transaction = self.service.withdraw(
            wallet=self.wallet1,
            amount=withdraw_amount,
            description='Test withdrawal'
        )
        
        self.assertEqual(transaction.transaction_type, TRANSACTION_TYPE_WITHDRAWAL)
        self.assertEqual(transaction.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(transaction.amount.amount, withdraw_amount)
        
        # Verify balance decreased
        self.wallet1.refresh_from_db()
        self.assertEqual(
            self.wallet1.balance.amount,
            initial_balance - withdraw_amount
        )
    
    def test_withdraw_insufficient_funds(self):
        """Test withdrawal fails with insufficient funds"""
        with self.assertRaises(InsufficientFunds):
            self.service.withdraw(
                wallet=self.wallet1,
                amount=Decimal('5000')  # More than balance
            )
    
    @patch('wallet.services.wallet_service.generate_transaction_reference')
    def test_withdraw_to_bank_success(self, mock_generate_ref):
        """Test successful bank withdrawal"""
        mock_generate_ref.return_value = 'TXN_bank_withdraw123'
        self.mock_paystack.initiate_transfer.return_value = {
            'transfer_code': 'TRF_test123',
            'status': 'pending',
            'reference': 'TXN_bank_withdraw123'
        }
        
        initial_balance = self.wallet1.balance.amount
        withdraw_amount = Decimal('200')
        
        transaction, transfer_data = self.service.withdraw_to_bank(
            wallet=self.wallet1,
            amount=withdraw_amount,
            bank_account=self.bank_account,
            reason='Test bank withdrawal'
        )
        
        self.assertEqual(transaction.transaction_type, TRANSACTION_TYPE_WITHDRAWAL)
        self.assertEqual(transaction.recipient_bank_account, self.bank_account)
        self.assertEqual(transaction.paystack_reference, 'TRF_test123')
        
        # Verify balance decreased
        self.wallet1.refresh_from_db()
        self.assertEqual(
            self.wallet1.balance.amount,
            initial_balance - withdraw_amount
        )
        
        # Verify Paystack transfer was initiated
        self.mock_paystack.initiate_transfer.assert_called_once()
    
    def test_withdraw_to_bank_no_recipient_code(self):
        """Test bank withdrawal fails without recipient code"""
        # Create bank account without recipient code
        account = BankAccount.objects.create(
            wallet=self.wallet1,
            bank=self.test_bank,
            account_number='9999999999',
            account_name='Test User'
        )
        
        with self.assertRaises(BankAccountError):
            self.service.withdraw_to_bank(
                wallet=self.wallet1,
                amount=Decimal('100'),
                bank_account=account
            )
    
    def test_withdraw_to_bank_wrong_wallet(self):
        """Test bank withdrawal fails with wrong wallet"""
        with self.assertRaises(BankAccountError):
            self.service.withdraw_to_bank(
                wallet=self.wallet2,  # Different wallet
                amount=Decimal('100'),
                bank_account=self.bank_account  # Belongs to wallet1
            )
    
    def test_withdraw_to_bank_paystack_failure(self):
        """Test bank withdrawal handles Paystack failure"""
        self.mock_paystack.initiate_transfer.side_effect = PaystackAPIError(
            "Transfer failed"
        )
        
        with self.assertRaises(PaystackAPIError):                                     
            self.service.withdraw_to_bank(
                wallet=self.wallet1,
                amount=Decimal('100'),
                bank_account=self.bank_account
            )
        
        # Verify transaction was marked as failed
        transaction = Transaction.objects.filter(
            wallet=self.wallet1,
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL
        ).first()
        
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, TRANSACTION_STATUS_FAILED)


class TransferOperationsTests(WalletServiceTestCase):
    """Tests for wallet-to-wallet transfer operations"""
    
    @patch('wallet.services.wallet_service.generate_transaction_reference')
    def test_transfer_success(self, mock_generate_ref):
        """Test successful wallet transfer"""
        mock_generate_ref.return_value = 'TXN_transfer123'
        
        source_initial = self.wallet1.balance.amount
        dest_initial = self.wallet2.balance.amount
        transfer_amount = Decimal('250')
        
        transaction = self.service.transfer(
            source_wallet=self.wallet1,
            destination_wallet=self.wallet2,
            amount=transfer_amount,
            description='Test transfer'
        )
        
        self.assertEqual(transaction.transaction_type, TRANSACTION_TYPE_TRANSFER)
        self.assertEqual(transaction.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(transaction.wallet, self.wallet1)
        self.assertEqual(transaction.recipient_wallet, self.wallet2)
        
        # Verify balances updated
        self.wallet1.refresh_from_db()
        self.wallet2.refresh_from_db()
        
        self.assertEqual(
            self.wallet1.balance.amount,
            source_initial - transfer_amount
        )
        self.assertEqual(
            self.wallet2.balance.amount,
            dest_initial + transfer_amount
        )
    
    def test_transfer_insufficient_funds(self):
        """Test transfer fails with insufficient funds"""
        with self.assertRaises(InsufficientFunds):
            self.service.transfer(
                source_wallet=self.wallet1,
                destination_wallet=self.wallet2,
                amount=Decimal('2000')  # More than balance
            )
    
    def test_transfer_to_locked_wallet(self):
        """Test transfer fails to locked wallet"""
        self.wallet2.is_active = False
        self.wallet2.save()
        
        with self.assertRaises(WalletLocked):
            self.service.transfer(
                source_wallet=self.wallet1,
                destination_wallet=self.wallet2,
                amount=Decimal('100')
            )
    
    def test_transfer_default_description(self):
        """Test transfer with auto-generated description"""
        transaction = self.service.transfer(
            source_wallet=self.wallet1,
            destination_wallet=self.wallet2,
            amount=Decimal('50')
        )
        
        self.assertIn(self.user2.email, transaction.description)


class CardOperationsTests(WalletServiceTestCase):
    """Tests for card operations"""
    
    @patch('wallet.services.wallet_service.generate_transaction_reference')
    def test_charge_saved_card_success(self, mock_generate_ref):
        """Test charging a saved card"""
        mock_generate_ref.return_value = 'TXN_card_charge123'
        self.mock_paystack.charge_authorization.return_value = {
            'status': 'success',
            'reference': 'TXN_card_charge123',
            'amount': 250000
        }
        
        charge_data = self.service.charge_saved_card(
            card=self.card,
            amount=Decimal('2500')
        )
        
        self.assertEqual(charge_data['status'], 'success')
        
        # Verify Paystack was called correctly
        self.mock_paystack.charge_authorization.assert_called_once()
        call_kwargs = self.mock_paystack.charge_authorization.call_args[1]
        self.assertEqual(call_kwargs['amount'], 250000)  # In kobo
        self.assertEqual(call_kwargs['authorization_code'], 'AUTH_test123')
    
    def test_charge_saved_card_with_metadata(self):
        """Test charging card with custom metadata"""
        self.mock_paystack.charge_authorization.return_value = {
            'status': 'success'
        }
        
        custom_metadata = {'order_id': '12345'}
        
        self.service.charge_saved_card(
            card=self.card,
            amount=Decimal('1000'),
            metadata=custom_metadata
        )
        
        call_kwargs = self.mock_paystack.charge_authorization.call_args[1]
        self.assertIn('order_id', call_kwargs['metadata'])
        self.assertIn('wallet_id', call_kwargs['metadata'])


class BankAccountOperationsTests(WalletServiceTestCase):
    """Tests for bank account operations"""
    
    def test_list_banks(self):
        """Test listing available banks"""
        self.mock_paystack.list_banks.return_value = [
            {'name': 'GTBank', 'code': '058'},
            {'name': 'Access Bank', 'code': '044'}
        ]
        
        banks = self.service.list_banks()
        
        self.assertEqual(len(banks), 2)
        self.mock_paystack.list_banks.assert_called_once()
    
    def test_verify_bank_account(self):
        """Test verifying bank account"""
        self.mock_paystack.resolve_account_number.return_value = {
            'account_number': '1234567890',
            'account_name': 'John Doe'
        }
        
        account_data = self.service.verify_bank_account('1234567890', '058')
        
        self.assertEqual(account_data['account_name'], 'John Doe')
        self.mock_paystack.resolve_account_number.assert_called_once_with(
            '1234567890', '058'
        )
    
    def test_add_bank_account_with_verification(self):
        """Test adding bank account with automatic verification"""
        self.mock_paystack.resolve_account_number.return_value = {
            'account_number': '0987654321',
            'account_name': 'Jane Doe'
        }
        self.mock_paystack.create_transfer_recipient.return_value = {
            'recipient_code': 'RCP_new123',
            'type': 'nuban'
        }
        
        bank_account = self.service.add_bank_account(
            wallet=self.wallet2,
            bank_code='058',
            account_number='0987654321'
        )
        
        self.assertEqual(bank_account.account_number, '0987654321')
        self.assertEqual(bank_account.account_name, 'Jane Doe')
        self.assertTrue(bank_account.is_verified)
        self.assertEqual(bank_account.paystack_recipient_code, 'RCP_new123')
        
        # Verify TransferRecipient was created
        recipient = TransferRecipient.objects.filter(
            wallet=self.wallet2,
            recipient_code='RCP_new123'
        ).first()
        self.assertIsNotNone(recipient)
    
    def test_add_bank_account_with_provided_name(self):
        """Test adding bank account with pre-provided account name"""
        self.mock_paystack.create_transfer_recipient.return_value = {
            'recipient_code': 'RCP_provided123'
        }
        
        bank_account = self.service.add_bank_account(
            wallet=self.wallet2,
            bank_code='058',
            account_number='1111222233',
            account_name='Provided Name'
        )
        
        self.assertEqual(bank_account.account_name, 'Provided Name')
        # Verify account was not verified via API
        self.mock_paystack.resolve_account_number.assert_not_called()
    
    def test_add_bank_account_verification_failure(self):
        """Test adding bank account when verification fails"""
        self.mock_paystack.resolve_account_number.side_effect = Exception(
            "Verification failed"
        )
        
        with self.assertRaises(BankAccountError):
            self.service.add_bank_account(
                wallet=self.wallet2,
                bank_code='058',
                account_number='9999999999'
            )
    
    def test_add_bank_account_invalid_bank_code(self):
        """Test adding bank account with invalid bank code"""
        with self.assertRaises(BankAccountError):
            self.service.add_bank_account(
                wallet=self.wallet2,
                bank_code='999',  # Non-existent bank code
                account_number='1234567890',
                account_name='Test User'
            )
    
    def test_add_bank_account_sets_as_default(self):
        """Test first bank account is set as default"""
        # Remove existing bank account
        BankAccount.objects.filter(wallet=self.wallet2).delete()
        
        self.mock_paystack.create_transfer_recipient.return_value = {
            'recipient_code': 'RCP_default123'
        }
        
        bank_account = self.service.add_bank_account(
            wallet=self.wallet2,
            bank_code='058',
            account_number='5555666677',
            account_name='Test User'
        )
        
        self.assertTrue(bank_account.is_default)


class TransactionHistoryTests(WalletServiceTestCase):
    """Tests for transaction history operations"""
    
    def setUp(self):
        super().setUp()
        
        # Create test transactions
        self.txn1 = Transaction.objects.create(
            wallet=self.wallet1,
            amount=Money(100, 'NGN'),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            description='Test deposit 1',
            reference='TXN_001'
        )
        
        self.txn2 = Transaction.objects.create(
            wallet=self.wallet1,
            amount=Money(50, 'NGN'),
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS,
            description='Test withdrawal 1',
            reference='TXN_002'
        )
        
        self.txn3 = Transaction.objects.create(
            wallet=self.wallet1,
            amount=Money(200, 'NGN'),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            description='Test deposit 2',
            reference='TXN_003'
        )
    
    def test_get_transaction_history_all(self):
        """Test getting all transactions"""
        transactions = self.service.get_transaction_history(self.wallet1)
        
        self.assertEqual(transactions.count(), 3)
    
    def test_get_transaction_history_by_type(self):
        """Test filtering by transaction type"""
        transactions = self.service.get_transaction_history(
            wallet=self.wallet1,
            transaction_type=TRANSACTION_TYPE_DEPOSIT
        )
        
        self.assertEqual(transactions.count(), 2)
        for txn in transactions:
            self.assertEqual(txn.transaction_type, TRANSACTION_TYPE_DEPOSIT)
    
    def test_get_transaction_history_by_status(self):
        """Test filtering by status"""
        transactions = self.service.get_transaction_history(
            wallet=self.wallet1,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(transactions.count(), 2)
        for txn in transactions:
            self.assertEqual(txn.status, TRANSACTION_STATUS_SUCCESS)
    
    def test_get_transaction_history_by_date_range(self):
        """Test filtering by date range"""
        from datetime import datetime, timedelta
        
        start_date = timezone.now() - timedelta(days=1)
        end_date = timezone.now() + timedelta(days=1)
        
        transactions = self.service.get_transaction_history(
            wallet=self.wallet1,
            start_date=start_date,
            end_date=end_date
        )
        
        self.assertEqual(transactions.count(), 3)
    
    def test_get_transaction_history_ordering(self):
        """Test transactions are ordered by most recent first"""
        transactions = list(self.service.get_transaction_history(self.wallet1))
        
        # Most recent should be first
        self.assertEqual(transactions[0].reference, 'TXN_003')
        self.assertEqual(transactions[-1].reference, 'TXN_001')
    
    def test_get_transaction_history_with_multiple_filters(self):
        """Test combining multiple filters"""
        transactions = self.service.get_transaction_history(
            wallet=self.wallet1,
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS
        )
        
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions[0].reference, 'TXN_001')


class EdgeCasesAndErrorHandlingTests(WalletServiceTestCase):
    """Tests for edge cases and error handling"""
    
    def test_deposit_invalid_amount_zero(self):
        """Test deposit with zero amount"""
        with self.assertRaises(InvalidAmount):
            self.service.deposit(
                wallet=self.wallet1,
                amount=Decimal('0')
            )
    
    def test_deposit_invalid_amount_negative(self):
        """Test deposit with negative amount"""
        with self.assertRaises(InvalidAmount):
            self.service.deposit(
                wallet=self.wallet1,
                amount=Decimal('-100')
            )
    
    def test_withdraw_invalid_amount_zero(self):
        """Test withdrawal with zero amount"""
        with self.assertRaises(InvalidAmount):
            self.service.withdraw(
                wallet=self.wallet1,
                amount=Decimal('0')
            )
    
    def test_transfer_to_same_wallet(self):
        """Test transfer to same wallet should fail"""
        with self.assertRaises(ValueError):
            self.service.transfer(                                             
                source_wallet=self.wallet1,
                destination_wallet=self.wallet1,
                amount=Decimal('100')
            )
    
    def test_transaction_rollback_on_failure(self):
        """Test that failed transactions don't affect balance"""
        initial_balance = self.wallet1.balance.amount
        
        # Mock wallet.withdraw to fail after transaction creation
        with patch.object(Wallet, 'withdraw', side_effect=Exception("Mock failure")):
            try:
                self.service.withdraw(
                    wallet=self.wallet1,
                    amount=Decimal('100')
                )
            except Exception:
                pass
        
        # Balance should remain unchanged
        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance.amount, initial_balance)
        
        # Failed transaction should exist
        failed_txn = Transaction.objects.filter(
            wallet=self.wallet1,                                                      
            status=TRANSACTION_STATUS_FAILED
        ).first()
        self.assertIsNotNone(failed_txn)
        self.assertIsNotNone(failed_txn.failed_reason)


class IntegrationTests(WalletServiceTestCase):
    """Integration tests for complex workflows"""
    
    def test_full_deposit_workflow(self):
        """Test complete deposit workflow from charge to completion"""
        # Step 1: Initialize charge
        self.mock_paystack.initialize_transaction.return_value = {
            'authorization_url': 'https://checkout.paystack.com/xyz',
            'access_code': 'access123',
            'reference': 'TXN_full_deposit'
        }
        
        charge_data = self.service.initialize_card_charge(
            wallet=self.wallet1,
            amount=Decimal('1000')
        )
        
        self.assertIn('authorization_url', charge_data)
        
        # Step 2: Complete deposit
        transaction = self.service.deposit(
            wallet=self.wallet1,
            amount=Decimal('1000'),
            transaction_reference=charge_data['reference']
        )
        
        self.assertEqual(transaction.status, TRANSACTION_STATUS_SUCCESS)
    
    def test_full_withdrawal_workflow(self):
        """Test complete withdrawal workflow"""
        # Step 1: Verify bank account
        self.mock_paystack.resolve_account_number.return_value = {
            'account_number': '1234567890',
            'account_name': 'Test User'
        }
        
        # Step 2: Add bank account
        self.mock_paystack.create_transfer_recipient.return_value = {
            'recipient_code': 'RCP_workflow123'
        }
        
        account_number = f"12345{random.randint(10000, 99999)}"  # makes a 10-digit number
        bank_account = self.service.add_bank_account(
            wallet=self.wallet1,
            bank_code='058',
            account_number=account_number
        )
        
        # Step 3: Withdraw to bank
        self.mock_paystack.initiate_transfer.return_value = {
            'transfer_code': 'TRF_workflow123',
            'status': 'pending'
        }
        
        transaction, transfer_data = self.service.withdraw_to_bank(
            wallet=self.wallet1,
            amount=Decimal('500'),
            bank_account=bank_account
        )
        
        self.assertEqual(transaction.recipient_bank_account, bank_account)
        self.assertIn('transfer_code', transfer_data)
    
    def test_wallet_to_wallet_transfer_workflow(self):
        """Test complete wallet-to-wallet transfer"""
        initial_source = self.wallet1.balance.amount
        initial_dest = self.wallet2.balance.amount
        transfer_amount = Decimal('300')
        
        transaction = self.service.transfer(
            source_wallet=self.wallet1,
            destination_wallet=self.wallet2,
            amount=transfer_amount,
            description='Integration test transfer'
        )
        
        # Verify transaction
        self.assertEqual(transaction.status, TRANSACTION_STATUS_SUCCESS)
        
        # Verify balances
        self.wallet1.refresh_from_db()
        self.wallet2.refresh_from_db()
        
        self.assertEqual(
            self.wallet1.balance.amount,
            initial_source - transfer_amount
        )
        self.assertEqual(
            self.wallet2.balance.amount,
            initial_dest + transfer_amount
        )
        
        # Verify transaction exists in history
        history = self.service.get_transaction_history(self.wallet1)
        self.assertIn(transaction, history)

    def tearDown(self):
        return super().tearDown()