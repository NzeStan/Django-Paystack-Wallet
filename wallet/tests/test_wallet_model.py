from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from djmoney.money import Money

from wallet.models.wallet import Wallet
from wallet.services.wallet_service import WalletService
from wallet.settings import get_wallet_setting
from wallet.exceptions import InvalidAmount, InsufficientFunds
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_STATUS_SUCCESS,
    BANK_ACCOUNT_TYPE_SAVINGS,
    CARD_TYPE_VISA,
)

User = get_user_model()
DEFAULT_CURRENCY = get_wallet_setting('CURRENCY')


class WalletModelTestCase(TestCase):
    """Test case for Wallet model."""

    def setUp(self):
        """Create two users and their wallets using the WalletService."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='testuser1@example.com',
            password='password123'
        )

        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        self.wallet1 = wallet_service.get_wallet(self.user1)

        # Give an initial Money balance to wallet (use Money object)
        self.wallet.balance = Money(1000, DEFAULT_CURRENCY)
        self.wallet.save()

    def test_wallet_creation(self):
        self.assertIsInstance(self.wallet, Wallet)
        self.assertEqual(self.wallet.user, self.user)
        self.assertEqual(self.wallet.balance, Money(1000, DEFAULT_CURRENCY))

    def test_wallet_str_representation(self):
        # Adapted to current __str__ implementation
        self.assertIn(str(self.user.email), str(self.wallet))
        self.assertIn(str(self.wallet.balance), str(self.wallet))

    def test_wallet_balance_update(self):
        initial_balance = self.wallet.balance
        deposit_amount = Money(500, DEFAULT_CURRENCY)
        self.wallet.balance += deposit_amount
        self.wallet.save()
        self.assertEqual(self.wallet.balance, initial_balance + deposit_amount)

    def test_wallet_multiple_users(self):
        self.assertNotEqual(self.wallet.user, self.wallet1.user)
        self.assertEqual(self.wallet1.balance, Money(0, DEFAULT_CURRENCY))

    def test_wallet_transaction_types_constants(self):
        self.assertEqual(TRANSACTION_TYPE_DEPOSIT, 'deposit')
        self.assertEqual(TRANSACTION_STATUS_SUCCESS, 'success')
        self.assertEqual(BANK_ACCOUNT_TYPE_SAVINGS, 'savings')
        self.assertEqual(CARD_TYPE_VISA, 'visa')

    def test_check_active_wallet(self):
        self.assertTrue(self.wallet.is_active)
        self.wallet.is_active = False
        self.wallet.save()
        self.assertFalse(self.wallet.is_active)

    def test_validate_amount_instance_method(self):
        # validate_amount is an instance method and returns a Money object
        self.assertEqual(self.wallet.validate_amount(100.00), Money(100.00, DEFAULT_CURRENCY))
        self.assertEqual(self.wallet.validate_amount(Decimal('0.01')), Money(Decimal('0.01'), DEFAULT_CURRENCY))
        with self.assertRaises(InvalidAmount):
            self.wallet.validate_amount(-50.00)
        with self.assertRaises(InvalidAmount):
            self.wallet.validate_amount(0.00)

    def test_lock_and_unlock_wallet(self):
        self.assertFalse(self.wallet.is_locked)
        self.wallet.lock()
        self.wallet.refresh_from_db()
        self.assertTrue(self.wallet.is_locked)

        self.wallet.unlock()
        self.wallet.refresh_from_db()
        self.assertFalse(self.wallet.is_locked)

    def test_activate_and_deactivate_wallet(self):
        self.wallet.deactivate()
        self.wallet.refresh_from_db()
        self.assertFalse(self.wallet.is_active)

        self.wallet.activate()
        self.wallet.refresh_from_db()
        self.assertTrue(self.wallet.is_active)

    def test_reset_daily_limit_and_update_metrics(self):
        # Use the fields your model defines: daily_transaction_total, daily_transaction_count
        self.wallet.daily_transaction_total = Money(500, DEFAULT_CURRENCY)
        self.wallet.daily_transaction_count = 2
        self.wallet.save()

        # reset_daily_limit is a method on the instance
        self.wallet.reset_daily_limit()
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.daily_transaction_total, Money(0, DEFAULT_CURRENCY))
        self.assertEqual(self.wallet.daily_transaction_count, 0)

        # update_transaction_metrics expects a numeric amount (it converts to Money internally)
        self.wallet.update_transaction_metrics(200.00)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.daily_transaction_total, Money(200.00, DEFAULT_CURRENCY))
        self.assertEqual(self.wallet.daily_transaction_count, 1)

    def test_deposit_and_withdraw(self):
        initial_balance = self.wallet.balance

        # deposit
        returned = self.wallet.deposit(300.00)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance + Money(300.00, DEFAULT_CURRENCY))
        self.assertEqual(returned, self.wallet.balance)

        # withdraw successful
        initial_balance = self.wallet.balance
        returned = self.wallet.withdraw(400.00)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance - Money(400.00, DEFAULT_CURRENCY))
        self.assertEqual(returned, self.wallet.balance)

        # withdraw insufficient funds -> InsufficientFunds
        with self.assertRaises(InsufficientFunds):
            self.wallet.withdraw(2000000.00)

    def test_transfer_between_wallets(self):
        # ensure wallet1 has zero balance
        self.assertEqual(self.wallet1.balance, Money(0, DEFAULT_CURRENCY))

        initial_sender = self.wallet.balance
        initial_receiver = self.wallet1.balance

        self.wallet.transfer(self.wallet1, 250.00)
        self.wallet.refresh_from_db()
        self.wallet1.refresh_from_db()

        self.assertEqual(self.wallet.balance, initial_sender - Money(250.00, DEFAULT_CURRENCY))
        self.assertEqual(self.wallet1.balance, initial_receiver + Money(250.00, DEFAULT_CURRENCY))

        # transfer should raise on insufficient funds
        with self.assertRaises(InsufficientFunds):
            self.wallet.transfer(self.wallet1, 99999999.00)

    def test_refresh_balance(self):
        # change directly in DB then call refresh_balance to update instance
        self.wallet.balance = Money(1500.00, DEFAULT_CURRENCY)
        self.wallet.save()
        # call instance method (it refreshes from db); it doesn't return the value
        self.wallet.refresh_balance()
        self.assertEqual(self.wallet.balance, Money(1500.00, DEFAULT_CURRENCY))

    def test_transaction_count_helpers_and_pending(self):
        self.assertEqual(self.wallet.get_transaction_count(), 0)
        self.assertEqual(self.wallet.get_successful_transactions_count(), 0)
        self.assertEqual(self.wallet.get_pending_transactions_count(), 0)
        self.assertFalse(self.wallet.has_pending_transactions())

    
    def tearDown(self):
        return super().tearDown()