from django.test import TestCase
from django.contrib.auth import get_user_model
from djmoney.money import Money
from wallet.models import (
    Wallet, Transaction
)
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_STATUS_SUCCESS
)

User = get_user_model()


class TransactionModelTestCase(TestCase):
    """Test the Transaction model"""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the transaction model"""
        # Create a user for testing
        cls.user = User.objects.create_user(
            username = "testuser",
            email='test@example.com',
            password='password123',
            first_name='Test',
            last_name='User'
        )

        cls.wallet, created = Wallet.objects.get_or_create(
            user = cls.user,
        )

        cls.transaction = Transaction.objects.create(
            wallet=cls.wallet,
            amount= Money(1000, "NGN"),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            description="Test transaction",
            reference="TX123456"
        )

        cls.transaction2 = Transaction.objects.create(
            wallet=cls.wallet,
            amount= Money(1000, "NGN"),
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            description="Test transaction",
        )

    def test_transaction_creation(self):
        """Test that a transaction is created correctly"""
        self.assertEqual(self.transaction.status, TRANSACTION_STATUS_SUCCESS)
        self.assertEqual(self.transaction.transaction_type, TRANSACTION_TYPE_DEPOSIT)
        self.assertEqual(self.transaction.reference, "TX123456")
    
    def test_transaction_reference_generation(self):
        """Test that a transaction reference is generated automatically"""
        
        self.assertIsNotNone(self.transaction2.reference)
        self.assertGreater(len(self.transaction2.reference), 0)
    
    def test_transaction_is_completed_property(self):
        """Test the is_completed property"""
        self.assertTrue(self.transaction.is_completed)
        
        # Change status to pending
        self.transaction.status = 'pending'
        self.transaction.save()
        
        # Refresh from DB
        self.transaction.refresh_from_db()
        self.assertFalse(self.transaction.is_completed)
        
    