from django.test import TestCase
from django.contrib.auth import get_user_model
from wallet.models import Wallet
from djmoney.money import Money
from django.utils import timezone
from decimal import Decimal
from wallet.exceptions import InsufficientFunds, WalletLocked, InvalidAmount, CurrencyMismatchError

User = get_user_model()

class WalletModelTestCase(TestCase):
    """Test the Wallet model"""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the wallet model"""
        # Create a user for testing
        cls.user = User.objects.create_user(
            username = "testuser",
            email='test@example.com',
            password='password123',
            first_name='Test',
            last_name='User'
        )
        cls.user1 = User.objects.create_user(
            username = "testuser1",
            email='test@example1.com',
            password='password123',
            first_name='Test1',
            last_name='User1'
        )

        cls.wallet, created = Wallet.objects.get_or_create(
            user = cls.user,
            balance = Money(Decimal('50000.00'), 'NGN')
        )

        cls.wallet1, created = Wallet.objects.get_or_create(
            user = cls.user1,
        )

    def test_wallet_creation(self):
        """Testing wallet creation"""
        self.assertIsInstance(self.wallet, Wallet)
        self.assertEqual(self.wallet.user, self.user)
        self.assertEqual(self.wallet.balance, Money(Decimal('50000.00'), 'NGN'))
        self.assertTrue(self.wallet.is_active)
        self.assertFalse(self.wallet.is_locked)
    
    def test_reset_daily_limit(self):
        """Test resetting daily transaction limits"""
        # Set some transaction metrics
        self.wallet.daily_transaction_total = Money(1000, self.wallet.balance.currency)
        self.wallet.daily_transaction_count = 5
        self.wallet.daily_transaction_reset = timezone.now().date() - timezone.timedelta(days=1)
        self.wallet.save()

        # Reset daily limit
        self.wallet.reset_daily_limit()

        # Assert metrics are reset
        self.assertEqual(self.wallet.daily_transaction_total.amount, 0)
        self.assertEqual(self.wallet.daily_transaction_count, 0)
        self.assertEqual(self.wallet.daily_transaction_reset, timezone.now().date())
    
    def test_update_transanction_metrics(self):
        """Test update transaction metrics """
        amount = Money(Decimal("1000.00"), "NGN")
        self.wallet.update_transaction_metrics(amount)

        self.assertEqual(self.wallet.daily_transaction_total, amount)
        self.assertEqual(self.wallet.daily_transaction_count, 1)
        self.assertEqual(self.wallet.daily_transaction_reset, timezone.now().date())

    def test_wallet_deposit(self):
        """Test wallet deposit functionality"""

        deposit_amount = Money(Decimal('2000.00'), 'NGN')
        
        new_balance = self.wallet.deposit(deposit_amount)
        
        # Assert the balance is updated correctly
        self.assertEqual(self.wallet.balance, new_balance)

    def test_wallet_withdraw(self):
        """Test wallet withdrawal functionality"""

        withdraw_amount = Money(Decimal('1000.00'), 'NGN')
        
        new_balance = self.wallet.withdraw(withdraw_amount)
        
        # Assert the balance is updated correctly
        self.assertEqual(self.wallet.balance, new_balance)

    def test_wallet_transfer(self):
        """Test wallet transfer functionality"""

        new_balance, new_destination_balance = self.wallet.transfer(
            destination_wallet=self.wallet1,
            amount=Money(Decimal('500.00'), 'NGN'),
            description='Test transfer'
        )

        # Assert the balances are updated correctly
        self.assertEqual(self.wallet.balance, new_balance)
        self.assertEqual(self.wallet1.balance, new_destination_balance)
        self.assertEqual(self.wallet1.user, self.user1)

        
    def test_wallet_lock(self):
            """Testing wallet lock and unlock functionality"""
            # Assume is_locked is False by default
            self.assertFalse(self.wallet.is_locked)

            # Lock it
            self.wallet.lock()

            # Confirm it's saved to the DB
            self.wallet.refresh_from_db()
            self.assertTrue(self.wallet.is_locked)


    def test_wallet_active(self):
            """Testing wallet active status"""
            # Assume is_active is True by default
            self.assertTrue(self.wallet.is_active)

            # Deactivate it
            self.wallet.is_active = False
            self.wallet.save()

            # Confirm it's saved to the DB
            self.wallet.refresh_from_db()
            self.assertFalse(self.wallet.is_active)

            # Reactivate it
            self.wallet.is_active = True
            self.wallet.save()
            # Confirm it's saved to the DB
            self.wallet.refresh_from_db()
            self.assertTrue(self.wallet.is_active)

    def test_wallet_transfer_invalid_amount(self):
        """Testing transfer with invalid amount"""

        # Test with zero amount
        with self.assertRaises(InvalidAmount):
            self.wallet.transfer(self.wallet1, Money(Decimal('0.00'), 'NGN'))

        # Test with negative amount
        with self.assertRaises(InvalidAmount):
            self.wallet.transfer(self.wallet1, Money(Decimal('-100.00'), 'NGN'))

        # Test with non-numeric object
        with self.assertRaises(InvalidAmount):
            self.wallet.transfer(self.wallet1, 'invalid_amount')

    def test_wallet_withdrawal_insufficient_funds(self):
        """Testing withdrawal with insufficient funds"""
        withdraw_amount = Money(Decimal('100000.00'), 'NGN')
        
        with self.assertRaises(InsufficientFunds):
            self.wallet.withdraw(withdraw_amount)

    def test_wallet_transfer_insufficient_funds(self):
        """Testing transfer with insufficient funds"""
        
        # Try to transfer more than available balance
        transfer_amount = Money(Decimal('100000.00'), 'NGN')
        
        with self.assertRaises(InsufficientFunds):
            self.wallet.transfer(self.wallet1, transfer_amount)

    def test_wallet_transfer_currency_mismatch(self):
        """Testing transfer with currency mismatch"""
        
        # Set destination wallet to USD (assuming source is NGN)
        self.wallet1.balance = Money(Decimal('0.00'), 'USD')
        self.wallet.save()
        
        # Try to transfer with currency mismatch
        transfer_amount = Money(Decimal('100.00'), 'NGN')
        
        with self.assertRaises(CurrencyMismatchError):
            self.wallet.transfer(self.wallet1, transfer_amount)

    def test_wallet_transfer_invalid_amount(self):
        """Testing transfer with invalid amount"""
        
        # Test with zero amount
        with self.assertRaises(InvalidAmount):
            self.wallet.transfer(self.wallet1, Money(Decimal('0.00'), 'NGN'))

        # Test with negative amount
        with self.assertRaises(InvalidAmount):
            self.wallet.transfer(self.wallet1, Money(Decimal('-100.00'), 'NGN'))

        # Test with non-numeric object
        with self.assertRaises(InvalidAmount):
            self.wallet.transfer(self.wallet1, 'invalid_amount')

    def test_wallet_lock_unlock(self):
        """Test locking and unlocking a wallet with deposit"""
        # Lock wallet
        self.wallet.lock()
        self.assertTrue(self.wallet.is_locked)
        
        # Try to deposit - should raise exception
        with self.assertRaises(WalletLocked):
            self.wallet.deposit(Money(Decimal('100.00'), 'NGN'))
        
        # Unlock wallet
        self.wallet.unlock()
        self.assertFalse(self.wallet.is_locked)
        
        # Deposit should work now
        deposit_amount = Money(Decimal('100.00'), 'NGN')
        new_balance = self.wallet.deposit(deposit_amount)
        
        # Check the result
        self.assertEqual(self.wallet.balance, new_balance)
