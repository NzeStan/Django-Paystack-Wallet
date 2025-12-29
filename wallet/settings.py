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
    'TRANSACTION_CHARGE_PERCENT': getattr(settings, 'WALLET_TRANSACTION_CHARGE_PERCENT', 1.5),  # ✅ IMPLEMENT
    
    # Settlement
    'AUTO_SETTLEMENT': getattr(settings, 'WALLET_AUTO_SETTLEMENT', False),
    
    # Export Settings
    'EXPORT_PAGESIZE': getattr(settings, 'WALLET_EXPORT_PAGESIZE', 'A4'),
    'EXPORT_ORIENTATION': getattr(settings, 'WALLET_EXPORT_ORIENTATION', 'portrait'),
    
    # Email Notifications (TODO: Implement or remove)
    'SEND_EMAIL_NOTIFICATIONS': getattr(settings, 'WALLET_SEND_EMAIL_NOTIFICATIONS', False),  # Changed to False
    'EMAIL_SENDER': getattr(settings, 'WALLET_EMAIL_SENDER', 
                           settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else ''),
}

def get_wallet_setting(name):
    """
    Helper function to get a specific wallet setting
    """
    if name not in WALLET_SETTINGS:
        raise ValueError(f"Unknown setting: {name}")
    return WALLET_SETTINGS[name]