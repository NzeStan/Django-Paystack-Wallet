from django.test import TestCase
from django.contrib.auth import get_user_model
from wallet.models import Wallet, Bank, BankAccount

User = get_user_model()


class CModelTestCase(TestCase):
    """Test the BankAccount model"""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the card bank account model"""
        # Create a user for testing
        cls.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            first_name="Test",
            last_name="User",
        )

        cls.wallet, created = Wallet.objects.get_or_create(
            user=cls.user,
        )

        cls.bank = Bank.objects.create(
            name = "Test Bank",
            code = "123",
            slug= "test-bank",
        )

        cls.bank_account = BankAccount.objects.create(
            wallet=cls.wallet,
            bank=cls.bank,
            account_number="1234567890",
            account_name="Test User",
        )


    def test_bank_account_creation(self):
        """Test that a bank account is created successfully"""
        
        self.assertEqual(self.bank_account.account_number, "1234567890")
        self.assertEqual(self.bank_account.account_name, "Test User")
        self.assertEqual(self.bank_account.wallet, self.wallet)
        self.assertEqual(self.bank_account.bank, self.bank)

    def test_set_as_default(self):
        """Test that bank account can be set as default"""
        self.bank_account.set_as_default()
        self.assertTrue(self.bank_account.is_default)
        self.assertTrue(self.bank_account.wallet.bank_accounts.filter(is_default=True).exists())

    def test_remove(self):
        """Test that bank account can be marked as inactive"""
        self.bank_account.remove()
        self.assertFalse(self.bank_account.is_active)
        self.assertFalse(self.bank_account.is_default)
        self.assertFalse(self.wallet.bank_accounts.filter(is_active=True, is_default=True).exists())
        
        # Check if another account is set as default
        if self.wallet.bank_accounts.filter(is_active=True).exists():
            new_default = self.wallet.bank_accounts.filter(is_active=True).first()
            self.assertTrue(new_default.is_default)
            self.assertNotEqual(new_default.pk, self.bank_account.pk)

