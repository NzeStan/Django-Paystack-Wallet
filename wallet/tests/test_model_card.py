from django.test import TestCase
from django.contrib.auth import get_user_model
from wallet.models import Wallet, Card

User = get_user_model()


class CModelTestCase(TestCase):
    """Test the Card model"""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the card model"""
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

        cls.card = Card.objects.create(
            wallet=cls.wallet,
            last_four = "1234",
            expiry_month = "5/23",
            expiry_year = "2024",
        )

    def test_card_creation(self):
        """Test that a card is created successfully"""

        self.assertEqual(self.card.last_four, "1234")
        self.assertEqual(self.card.expiry_month, "5/23")
        self.assertEqual(self.card.expiry_year, "2024")

    def test_card_set_default(self):
        """Test that a card can be set as default"""
        self.card.set_as_default()
        self.assertTrue(self.card.is_default)
        self.assertTrue(self.card.wallet.cards.filter(is_default=True).exists())

    def test_card_remove(self):
        """Test that a card can be marked as inactive"""
        self.card.remove()
        self.assertFalse(self.card.is_active)
        self.assertFalse(self.card.is_default)
        self.assertFalse(self.wallet.cards.filter(is_active=True, is_default=True).exists())

    def test_card_is_expired(self):
        """Test that the card expiration check works"""
        self.card.expiry_year = "2020"
        self.assertTrue(self.card.is_expired)

        self.card.expiry_year = "2025"
        self.card.expiry_month = "12"
        self.assertFalse(self.card.is_expired)

        # Test with current date
        from datetime import datetime
        now = datetime.now()
        self.card.expiry_year = str(now.year)
        self.card.expiry_month = str(now.month + 1)
        self.assertFalse(self.card.is_expired)

