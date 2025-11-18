from django.conf import settings
from django.utils.translation import gettext_lazy as _

# Default settings for the wallet app
WALLET_SETTINGS = {
    # Use UUID instead of ID as primary key
    'USE_UUID': getattr(settings, 'WALLET_USE_UUID', True),
    
    # Use celery for asynchronous tasks
    'USE_CELERY': getattr(settings, 'WALLET_USE_CELERY', False),     #still switch to true

    # Paystack Configuration
    'PAYSTACK_SECRET_KEY': getattr(settings, 'PAYSTACK_SECRET_KEY', ''),
    'PAYSTACK_PUBLIC_KEY': getattr(settings, 'PAYSTACK_PUBLIC_KEY', ''),
    'PAYSTACK_API_URL': getattr(settings, 'PAYSTACK_API_URL', 'https://api.paystack.co'),
    
    # Transaction Settings
    'CURRENCY': getattr(settings, 'WALLET_CURRENCY', 'NGN'),
    'TRANSACTION_CHARGE_PERCENT': getattr(settings, 'WALLET_TRANSACTION_CHARGE_PERCENT', 1.5), ###
    'MINIMUM_BALANCE': getattr(settings, 'WALLET_MINIMUM_BALANCE', 0), ###
    'MAXIMUM_DAILY_TRANSACTION': getattr(settings, 'WALLET_MAXIMUM_DAILY_TRANSACTION', 1000000), ###
    
    # User model where wallet is attached
    'USER_MODEL': getattr(settings, 'AUTH_USER_MODEL', 'auth.User'),
    
    # Webhook Settings ###
    'WEBHOOK_SECRET': getattr(settings, 'WALLET_WEBHOOK_SECRET', ''),
    'WEBHOOK_URL': getattr(settings, 'WALLET_WEBHOOK_URL', '/wallet/webhook/'),
    
    # Logging Settings ###
    'LOG_LEVEL': getattr(settings, 'WALLET_LOG_LEVEL', 'INFO'),
    'LOG_FILE': getattr(settings, 'WALLET_LOG_FILE', 'wallet.log'),
    
    # Auto-create wallet for new users
    'AUTO_CREATE_WALLET': getattr(settings, 'WALLET_AUTO_CREATE_WALLET', True),
    
    # Email notification settings ###
    'SEND_EMAIL_NOTIFICATIONS': getattr(settings, 'WALLET_SEND_EMAIL_NOTIFICATIONS', True),
    'EMAIL_SENDER': getattr(settings, 'WALLET_EMAIL_SENDER', settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else ''),
    
    # Admin export settings
    'EXPORT_PAGESIZE': getattr(settings, 'WALLET_EXPORT_PAGESIZE', 'A4'),
    'EXPORT_ORIENTATION': getattr(settings, 'WALLET_EXPORT_ORIENTATION', 'portrait'),
    
    # Settlement settings
    'AUTO_SETTLEMENT': getattr(settings, 'WALLET_AUTO_SETTLEMENT', False),
    'SETTLEMENT_CRON': getattr(settings, 'WALLET_SETTLEMENT_CRON', '0 0 * * *'),  # Default to midnight daily ###
}

def get_wallet_setting(name):
    """
    Helper function to get a specific wallet setting
    """
    if name not in WALLET_SETTINGS:
        raise ValueError(f"Unknown setting: {name}")
    return WALLET_SETTINGS[name]