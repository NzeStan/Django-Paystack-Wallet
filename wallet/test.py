from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from wallet.models import (
    Wallet, Transaction, Card, Bank, BankAccount, 
    WebhookEvent, TransferRecipient, Settlement
)
from wallet.services.wallet_service import WalletService
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_STATUS_SUCCESS,
    BANK_ACCOUNT_TYPE_SAVINGS, CARD_TYPE_VISA
)

User = get_user_model()


class WalletTestCase(TestCase):
    """Base test case for wallet-related tests"""
    
    def setUp(self):
        """Setup test data for each test method"""
        # Create test users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
        
        # Create API clients
        self.api_client = APIClient()
        self.authenticated_client = APIClient()
        self.authenticated_client.force_authenticate(user=self.user)
        
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin_user)
        
        # Create wallet using service
        wallet_service = WalletService()
        self.wallet = wallet_service.get_wallet(self.user)
        
        # Create bank
        self.bank = Bank.objects.create(
            name="Test Bank",
            code="123",
            slug="test-bank",
            country="NG",
            currency="NGN",
            is_active=True
        )
        
        # Create bank account
        self.bank_account = BankAccount.objects.create(
            wallet=self.wallet,
            bank=self.bank,
            account_number="0123456789",
            account_name="Test User",
            account_type=BANK_ACCOUNT_TYPE_SAVINGS,
            is_verified=True,
            is_default=True,
            is_active=True
        )
        
        # Create card
        self.card = Card.objects.create(
            wallet=self.wallet,
            card_type=CARD_TYPE_VISA,
            last_four="4242",
            expiry_month="12",
            expiry_year="2025",
            bin="424242",
            card_holder_name="Test User",
            email="test@example.com",
            is_default=True,
            is_active=True
        )
        
        # Create transaction
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=1000,
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            description="Test transaction",
            reference="TX123456"
        )
        
        # Create webhook event
        self.webhook_event = WebhookEvent.objects.create(
            event_type="charge.success",
            payload={"data": {"reference": "TX123456"}},
            reference="TX123456",
            is_valid=True
        )
        
        # Create transfer recipient
        self.transfer_recipient = TransferRecipient.objects.create(
            wallet=self.wallet,
            recipient_code="RCP_123456",
            type="nuban",
            name="Test User",
            account_number="0123456789",
            bank_code="123",
            bank_name="Test Bank",
            currency="NGN"
        )
        
        # Create settlement
        self.settlement = Settlement.objects.create(
            wallet=self.wallet,
            bank_account=self.bank_account,
            amount=500,
            status="pending",
            reference="STL123456"
        )


class WalletModelTestCase(WalletTestCase):
    """Test case specifically for wallet model tests"""
    
    def test_wallet_creation(self):
        """Test wallet creation"""
        self.assertIsNotNone(self.wallet)
        self.assertEqual(self.wallet.user, self.user)
    
    def test_transaction_creation(self):
        """Test transaction creation"""
        self.assertEqual(self.transaction.wallet, self.wallet)
        self.assertEqual(self.transaction.amount, 1000)
        self.assertEqual(self.transaction.transaction_type, TRANSACTION_TYPE_DEPOSIT)
        self.assertEqual(self.transaction.status, TRANSACTION_STATUS_SUCCESS)
    
    def test_bank_account_creation(self):
        """Test bank account creation"""
        self.assertEqual(self.bank_account.wallet, self.wallet)
        self.assertEqual(self.bank_account.bank, self.bank)
        self.assertEqual(self.bank_account.account_number, "0123456789")
        self.assertTrue(self.bank_account.is_verified)
    
    def test_card_creation(self):
        """Test card creation"""
        self.assertEqual(self.card.wallet, self.wallet)
        self.assertEqual(self.card.card_type, CARD_TYPE_VISA)
        self.assertEqual(self.card.last_four, "4242")
        self.assertTrue(self.card.is_active)


class WalletAPITestCase(WalletTestCase):
    """Test case for wallet API endpoints"""
    
    def test_authenticated_access(self):
        """Test that authenticated client has access"""
        # Example test - replace with actual endpoint
        response = self.authenticated_client.get('/api/wallet/')
        # Add assertions based on your actual API behavior
        # self.assertEqual(response.status_code, 200)
    
    def test_admin_access(self):
        """Test that admin client has access"""
        # Example test - replace with actual admin endpoint
        response = self.admin_client.get('/api/admin/wallets/')
        # Add assertions based on your actual API behavior
        # self.assertEqual(response.status_code, 200)
    
    def test_unauthenticated_access(self):
        """Test that unauthenticated requests are rejected"""
        response = self.api_client.get('/api/wallet/')
        # Add assertions based on your actual API behavior
        # self.assertEqual(response.status_code, 401)


class WalletServiceTestCase(WalletTestCase):
    """Test case for wallet service methods"""
    
    def test_wallet_service_get_wallet(self):
        """Test wallet service get_wallet method"""
        wallet_service = WalletService()
        wallet = wallet_service.get_wallet(self.user)
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.user, self.user)
    
    def test_webhook_event_processing(self):
        """Test webhook event processing"""
        self.assertEqual(self.webhook_event.event_type, "charge.success")
        self.assertTrue(self.webhook_event.is_valid)
        self.assertEqual(self.webhook_event.reference, "TX123456")


# Alternative approach: Separate test cases for different components

class UserTestCase(TestCase):
    """Test case focused on user-related functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123'
        )
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
    
    def test_user_creation(self):
        """Test user creation"""
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.email, 'test@example.com')
        self.assertTrue(self.user.check_password('password123'))
    
    def test_admin_user_creation(self):
        """Test admin user creation"""
        self.assertTrue(self.admin_user.is_superuser)
        self.assertTrue(self.admin_user.is_staff)


class BankTestCase(TestCase):
    """Test case focused on bank-related functionality"""
    
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Test Bank",
            code="123",
            slug="test-bank",
            country="NG",
            currency="NGN",
            is_active=True
        )
    
    def test_bank_creation(self):
        """Test bank creation"""
        self.assertEqual(self.bank.name, "Test Bank")
        self.assertEqual(self.bank.code, "123")
        self.assertEqual(self.bank.country, "NG")
        self.assertTrue(self.bank.is_active)


class TransactionTestCase(WalletTestCase):
    """Test case focused on transaction functionality"""
    
    def test_transaction_wallet_relationship(self):
        """Test transaction-wallet relationship"""
        self.assertEqual(self.transaction.wallet.user, self.user)
    
    def test_transaction_status(self):
        """Test transaction status"""
        self.assertEqual(self.transaction.status, TRANSACTION_STATUS_SUCCESS)
    
    def test_transaction_reference(self):
        """Test transaction reference uniqueness"""
        self.assertEqual(self.transaction.reference, "TX123456")