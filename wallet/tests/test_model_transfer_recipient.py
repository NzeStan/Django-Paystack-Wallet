from django.test import TestCase
from django.contrib.auth import get_user_model
from wallet.models import Wallet, TransferRecipient

User = get_user_model()


class TransferReceiptentModelTestCase(TestCase):
    """Test the TransferReceiptent model"""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the transfer receipent model"""
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

        cls.recipient = TransferRecipient.objects.create(
            wallet=cls.wallet,
            recipient_code="dgrtyer56",
            type="nuban",
            name="ifeanyi nnamani",
        )

    def test_recipient_creation(self):
        """Test that a receipent is created successfully"""

        self.assertEqual(self.recipient.recipient_code, "dgrtyer56")
        self.assertEqual(self.recipient.type, "nuban")
        self.assertEqual(self.recipient.name, "ifeanyi nnamani")

    def test_recipient_deactivation(self):
        """Test that a recipient can be deactivated"""
        self.recipient.is_active = False
        self.recipient.save()

        self.assertFalse(self.recipient.is_active)

