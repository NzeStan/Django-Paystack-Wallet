from django.conf import settings
from django.utils.translation import gettext_lazy as _

# Default settings for the wallet app
WALLET_SETTINGS = {
    # Primary Keys
    'USE_UUID': getattr(settings, 'WALLET_USE_UUID', True),

    # User model where wallet is attached
    'USER_MODEL': getattr(settings, 'AUTH_USER_MODEL', 'auth.User'),
    
    # Async Processing
    'USE_CELERY': getattr(settings, 'WALLET_USE_CELERY', False),
    
    # Paystack Integration
    'PAYSTACK_SECRET_KEY': getattr(settings, 'PAYSTACK_SECRET_KEY', ''),
    'PAYSTACK_PUBLIC_KEY': getattr(settings, 'PAYSTACK_PUBLIC_KEY', ''),
    'PAYSTACK_API_URL': getattr(settings, 'PAYSTACK_API_URL', 'https://api.paystack.co'),
    'AUTO_SYNC_BANKS': getattr(settings, 'WALLET_AUTO_SYNC_BANKS', False),
    
    # Wallet Settings
    'CURRENCY': getattr(settings, 'WALLET_CURRENCY', 'NGN'),
    'AUTO_CREATE_WALLET': getattr(settings, 'WALLET_AUTO_CREATE_WALLET', True),
    
    # Transaction Limits
    'MINIMUM_BALANCE': getattr(settings, 'WALLET_MINIMUM_BALANCE', 0),
    'MAXIMUM_DAILY_TRANSACTION': getattr(settings, 'WALLET_MAXIMUM_DAILY_TRANSACTION', 1000000),
    
    # Settlement
    'AUTO_SETTLEMENT': getattr(settings, 'WALLET_AUTO_SETTLEMENT', False),
    
    # Export Settings
    'EXPORT_PAGESIZE': getattr(settings, 'WALLET_EXPORT_PAGESIZE', 'A4'),
    'EXPORT_ORIENTATION': getattr(settings, 'WALLET_EXPORT_ORIENTATION', 'portrait'),
    
    # Email Notifications
    'SEND_EMAIL_NOTIFICATIONS': getattr(settings, 'WALLET_SEND_EMAIL_NOTIFICATIONS', False),
    'EMAIL_SENDER': getattr(settings, 'WALLET_EMAIL_SENDER', 
                           settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else ''),
    
    # ==========================================
    # FEE CONFIGURATION
    # ==========================================
    
    # Master control - turn fees on/off globally
    'ENABLE_FEES': getattr(settings, 'WALLET_ENABLE_FEES', False),
    
    # Use database-driven fee configurations instead of settings
    'USE_DATABASE_FEE_CONFIG': getattr(settings, 'WALLET_USE_DATABASE_FEE_CONFIG', False),
    
    # Fee Bearer Options
    # Options: 'customer', 'merchant', 'platform', 'split'
    'DEFAULT_FEE_BEARER': getattr(settings, 'WALLET_DEFAULT_FEE_BEARER', 'platform'),
    
    # ==========================================
    # DEPOSIT/CARD TRANSACTION FEES
    # ==========================================
    
    # Local Card/USSD Fees (Nigeria Standard: 1.5% + NGN 100)
    'LOCAL_CARD_PERCENTAGE_FEE': getattr(settings, 'WALLET_LOCAL_CARD_PERCENTAGE_FEE', 1.5),
    'LOCAL_CARD_FLAT_FEE': getattr(settings, 'WALLET_LOCAL_CARD_FLAT_FEE', 100),
    'LOCAL_CARD_FEE_CAP': getattr(settings, 'WALLET_LOCAL_CARD_FEE_CAP', 2000),
    'LOCAL_CARD_FEE_WAIVER_THRESHOLD': getattr(settings, 'WALLET_LOCAL_CARD_FEE_WAIVER_THRESHOLD', 2500),
    
    # International Card Fees (3.9% + NGN 100)
    'INTL_CARD_PERCENTAGE_FEE': getattr(settings, 'WALLET_INTL_CARD_PERCENTAGE_FEE', 3.9),
    'INTL_CARD_FLAT_FEE': getattr(settings, 'WALLET_INTL_CARD_FLAT_FEE', 100),
    'INTL_CARD_FEE_CAP': getattr(settings, 'WALLET_INTL_CARD_FEE_CAP', None),  # No cap for intl
    
    # DVA (Dedicated Virtual Account) Fees (1% capped at NGN 300)
    'DVA_PERCENTAGE_FEE': getattr(settings, 'WALLET_DVA_PERCENTAGE_FEE', 1.0),
    'DVA_FLAT_FEE': getattr(settings, 'WALLET_DVA_FLAT_FEE', 0),
    'DVA_FEE_CAP': getattr(settings, 'WALLET_DVA_FEE_CAP', 300),
    
    # ==========================================
    # TRANSFER/WITHDRAWAL FEES (Bank Transfers)
    # ==========================================
    
    'ENABLE_TRANSFER_FEES': getattr(settings, 'WALLET_ENABLE_TRANSFER_FEES', True),
    
    # Tiered Transfer Fees (Paystack Standard)
    # List of dicts with 'max_amount' and 'fee' keys
    # max_amount=None means unlimited (for last tier)
    'TRANSFER_FEE_TIERS': getattr(settings, 'WALLET_TRANSFER_FEE_TIERS', [
        {'max_amount': 5000, 'fee': 10},
        {'max_amount': 50000, 'fee': 25},
        {'max_amount': None, 'fee': 50},  # None = unlimited
    ]),
    
    # ==========================================
    # WALLET-TO-WALLET TRANSFER FEES
    # ==========================================
    
    'ENABLE_INTERNAL_TRANSFER_FEES': getattr(settings, 'WALLET_ENABLE_INTERNAL_TRANSFER_FEES', False),
    'INTERNAL_TRANSFER_PERCENTAGE_FEE': getattr(settings, 'WALLET_INTERNAL_TRANSFER_PERCENTAGE_FEE', 0),
    'INTERNAL_TRANSFER_FLAT_FEE': getattr(settings, 'WALLET_INTERNAL_TRANSFER_FLAT_FEE', 0),
    'INTERNAL_TRANSFER_FEE_CAP': getattr(settings, 'WALLET_INTERNAL_TRANSFER_FEE_CAP', None),
    
    # ==========================================
    # CUSTOM FEE SPLITS
    # ==========================================
    
    # When bearer is 'split', define the split ratio (must sum to 100)
    'FEE_SPLIT_CUSTOMER_PERCENTAGE': getattr(settings, 'WALLET_FEE_SPLIT_CUSTOMER_PERCENTAGE', 50),
    'FEE_SPLIT_MERCHANT_PERCENTAGE': getattr(settings, 'WALLET_FEE_SPLIT_MERCHANT_PERCENTAGE', 50),
    
    # ==========================================
    # SPECIAL PRICING
    # ==========================================
    
    # Educational Institution Pricing (0.7% capped at NGN 1,500)
    'ENABLE_EDUCATIONAL_PRICING': getattr(settings, 'WALLET_ENABLE_EDUCATIONAL_PRICING', False),
    'EDUCATIONAL_CARD_PERCENTAGE_FEE': getattr(settings, 'WALLET_EDUCATIONAL_CARD_PERCENTAGE_FEE', 0.7),
    'EDUCATIONAL_CARD_FEE_CAP': getattr(settings, 'WALLET_EDUCATIONAL_CARD_FEE_CAP', 1500),
    'EDUCATIONAL_OTHER_FLAT_FEE': getattr(settings, 'WALLET_EDUCATIONAL_OTHER_FLAT_FEE', 300),
}

def get_wallet_setting(name):
    """
    Helper function to get a specific wallet setting
    """
    if name not in WALLET_SETTINGS:
        raise ValueError(f"Unknown setting: {name}")
    return WALLET_SETTINGS[name]