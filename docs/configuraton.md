# Configuration Guide

This guide details all the available configuration options for the Django Paystack Wallet system.

## Settings Reference

All settings should be added to your Django project's `settings.py` file.

### Core Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `PAYSTACK_SECRET_KEY` | Your Paystack secret key | `''` | `'sk_test_1234567890abcdef'` |
| `PAYSTACK_PUBLIC_KEY` | Your Paystack public key | `''` | `'pk_test_1234567890abcdef'` |
| `PAYSTACK_API_URL` | Paystack API base URL | `'https://api.paystack.co'` | `'https://api.paystack.co'` |
| `WALLET_USE_UUID` | Use UUID instead of auto-incrementing ID | `True` | `False` |
| `WALLET_CURRENCY` | Default currency for wallets | `'NGN'` | `'USD'` |
| `WALLET_AUTO_CREATE_WALLET` | Auto-create wallet for new users | `True` | `False` |
| `WALLET_USER_MODEL` | User model for wallet ownership | `settings.AUTH_USER_MODEL` | `'custom_auth.User'` |

### Transaction Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `WALLET_TRANSACTION_CHARGE_PERCENT` | Default transaction fee percentage | `1.5` | `2.5` |
| `WALLET_MINIMUM_BALANCE` | Minimum balance to maintain | `0` | `1000` |
| `WALLET_MAXIMUM_DAILY_TRANSACTION` | Maximum daily transaction amount | `1000000` | `500000` |

### Webhook Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `WALLET_WEBHOOK_SECRET` | Secret for webhook signature verification | `''` | `'your_webhook_secret'` |
| `WALLET_WEBHOOK_URL` | URL path for the webhook endpoint | `'/wallet/webhook/'` | `'/custom/webhook/path/'` |

### Settlement Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `WALLET_AUTO_SETTLEMENT` | Enable automatic settlements | `False` | `True` |
| `WALLET_SETTLEMENT_CRON` | Cron schedule for settlements | `'0 0 * * *'` | `'0 */6 * * *'` |

### Export Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `WALLET_EXPORT_PAGESIZE` | Page size for PDF exports | `'A4'` | `'letter'` |
| `WALLET_EXPORT_ORIENTATION` | Orientation for PDF exports | `'portrait'` | `'landscape'` |

### Logging Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `WALLET_LOG_LEVEL` | Log level for wallet operations | `'INFO'` | `'DEBUG'` |
| `WALLET_LOG_FILE` | File to log wallet operations | `'wallet.log'` | `'/var/log/wallet.log'` |

### Email Settings

| Setting | Description | Default | Example |
|---------|-------------|---------|---------|
| `WALLET_SEND_EMAIL_NOTIFICATIONS` | Send email notifications | `True` | `False` |
| `WALLET_EMAIL_SENDER` | Email address for notifications | `settings.DEFAULT_FROM_EMAIL` | `'wallet@example.com'` |

## Integration with Django REST Framework

If you're using Django REST Framework's authentication and permission classes, you may want to configure them in your `settings.py`:

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
```

## Celery Integration

For background tasks, configure Celery in your `settings.py`:

```python
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

CELERY_BEAT_SCHEDULE = {
    'process_due_settlement_schedules': {
        'task': 'wallet.tasks.process_due_settlement_schedules_task',
        'schedule': crontab(minute='0', hour='*/1'),  # Run hourly
    },
    'reset_daily_transaction_limits': {
        'task': 'wallet.tasks.reset_daily_transaction_limits_task',
        'schedule': crontab(minute='0', hour='0'),  # Run at midnight
    },
    'sync_banks_from_paystack': {
        'task': 'wallet.tasks.sync_banks_from_paystack_task',
        'schedule': crontab(minute='0', hour='0', day_of_week='1'),  # Run weekly
    },
}
```

## Custom Middleware (Optional)

If you want to automatically include the authenticated user's wallet in the request object, you can add this middleware:

```python
# In your app's middleware.py
from wallet.services.wallet_service import WalletService

class WalletMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.wallet_service = WalletService()

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            request.wallet = self.wallet_service.get_wallet(request.user)
        
        response = self.get_response(request)
        return response

# In settings.py
MIDDLEWARE = [
    # ... other middleware
    'yourapp.middleware.WalletMiddleware',
]
```

## Advanced URL Configuration

For more control over URL patterns, you can manually include specific endpoints:

```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from wallet.apis import (
    WalletViewSet, TransactionViewSet, CardViewSet,
    BankAccountViewSet, BankViewSet, SettlementViewSet,
    SettlementScheduleViewSet, paystack_webhook
)

# Create a router for the API viewsets
router = DefaultRouter()
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'cards', CardViewSet, basename='card')
router.register(r'bank-accounts', BankAccountViewSet, basename='bank-account')
router.register(r'banks', BankViewSet, basename='bank')
router.register(r'settlements', SettlementViewSet, basename='settlement')
router.register(r'settlement-schedules', SettlementScheduleViewSet, basename='settlement-schedule')

urlpatterns = [
    # API URLs
    path('api/', include(router.urls)),
    
    # Webhook URL
    path('webhook/', paystack_webhook, name='paystack-webhook'),
    
    # Optional: Direct wallet operations
    path('deposit/', WalletViewSet.as_view({'post': 'deposit'}), name='wallet-deposit'),
    path('withdraw/', WalletViewSet.as_view({'post': 'withdraw'}), name='wallet-withdraw'),
    path('transfer/', WalletViewSet.as_view({'post': 'transfer'}), name='wallet-transfer'),
]
```

## Customizing Admin Interface

You can customize the admin interface by creating your own admin classes that inherit from the package's admin classes:

```python
from django.contrib import admin
from wallet.admin import WalletAdmin as BaseWalletAdmin
from wallet.models import Wallet

class CustomWalletAdmin(BaseWalletAdmin):
    list_display = BaseWalletAdmin.list_display + ('custom_field',)
    
    def custom_field(self, obj):
        return f"Custom: {obj.tag}"
    custom_field.short_description = "Custom Field"

# Unregister original admin and register custom
admin.site.unregister(Wallet)
admin.site.register(Wallet, CustomWalletAdmin)
```

## Overriding Templates

To override the admin templates, create the following directory structure in your project:

```
templates/
└── admin/
    └── wallet/
        └── analytics/
            ├── wallet_analytics.html
            ├── transaction_analytics.html
            └── settlement_analytics.html
```

## Logging Configuration

For detailed logging of wallet operations, add this to your `settings.py`:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'wallet_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': WALLET_LOG_FILE,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'wallet': {
            'handlers': ['wallet_file'],
            'level': WALLET_LOG_LEVEL,
            'propagate': False,
        },
    },
}
```

## Next Steps

After configuring the wallet system, check out the [Usage Guide](usage.md) for examples of how to use the wallet system in your application.': crontab(minute='0', hour='*/1'),  # Run hourly
    },
    'reset_daily_transaction_limits': {
        'task': 'wallet.tasks.reset_daily_transaction_limits_task',
        'schedule