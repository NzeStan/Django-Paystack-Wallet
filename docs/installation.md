# Installation Guide

This guide will walk you through the process of installing and configuring the Django Paystack Wallet system.

## Prerequisites

- Python 3.8 or higher
- Django 3.2 or higher
- Paystack account with API keys
- PostgreSQL or MySQL database (recommended, but SQLite works for development)

## Installation Steps

### 1. Install the Package

```bash
pip install django-paystack-wallet
```

### 2. Add to Installed Apps

Add the wallet app to your `INSTALLED_APPS` in your Django project's `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'rest_framework',
    'wallet',
]
```

### 3. Configure Paystack Settings

Add your Paystack API keys and other wallet settings to your project's `settings.py`:

```python
# Paystack Configuration
PAYSTACK_SECRET_KEY = 'sk_test_your_secret_key'
PAYSTACK_PUBLIC_KEY = 'pk_test_your_public_key'
PAYSTACK_API_URL = 'https://api.paystack.co'

# Wallet Settings
WALLET_USE_UUID = True  # Use UUID instead of ID as primary key
WALLET_CURRENCY = 'NGN'  # Default currency
WALLET_AUTO_CREATE_WALLET = True  # Auto-create wallet for new users
WALLET_TRANSACTION_CHARGE_PERCENT = 1.5  # Default transaction charge
WALLET_MINIMUM_BALANCE = 0  # Minimum balance to maintain
WALLET_MAXIMUM_DAILY_TRANSACTION = 1000000  # Maximum daily transaction limit
WALLET_AUTO_SETTLEMENT = False  # Auto-settlement of wallet funds
```

### 4. Add URLs

Include the wallet URLs in your project's `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    ...
    path('wallet/', include('wallet.urls')),
]
```

### 5. Run Migrations

Run migrations to create the necessary database tables:

```bash
python manage.py migrate
```

### 6. Configure Webhooks

Set up your webhook URL in your Paystack dashboard:

1. Go to Paystack dashboard > Settings > API Keys & Webhooks
2. Add webhook URL: `https://your-domain.com/wallet/webhook/`
3. Make sure your webhook URL is accessible from the internet

### 7. Setup Celery (Optional but Recommended)

For background tasks like automatic settlements, it's recommended to use Celery:

1. Install Celery:
```bash
pip install celery
```

2. Configure Celery in your Django project:

```python
# settings.py
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

# Add periodic tasks for the wallet system
from celery.schedules import crontab

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
    'verify_pending_settlements': {
        'task': 'wallet.tasks.verify_pending_settlements_task',
        'schedule': crontab(minute='*/15'),  # Run every 15 minutes
    },
    'retry_failed_webhook_deliveries': {
        'task': 'wallet.tasks.retry_failed_webhook_deliveries_task',
        'schedule': crontab(minute='*/10'),  # Run every 10 minutes
    },
    'verify_bank_accounts': {
        'task': 'wallet.tasks.verify_bank_accounts_task',
        'schedule': crontab(minute='0', hour='*/3'),  # Run every 3 hours
    },
    'check_expired_cards': {
        'task': 'wallet.tasks.check_expired_cards_task',
        'schedule': crontab(minute='0', hour='0'),  # Run daily at midnight
    },
}
```

3. Create a `celery.py` file in your project directory:

```python
import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings')

app = Celery('your_project')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
```

4. Start Celery worker and beat:

```bash
celery -A your_project worker -l info
celery -A your_project beat -l info
```

## Verify Installation

To verify that the wallet system is properly installed, you can:

1. Check the admin interface to see wallet models (`/admin/wallet/`)
2. Test the API endpoints:
   - `/wallet/api/wallets/`
   - `/wallet/api/transactions/`
   - `/wallet/api/banks/`

## Advanced Configuration

### Custom User Model

If you're using a custom user model, make sure to set it in the wallet settings:

```python
# settings.py
WALLET_USER_MODEL = 'yourapp.CustomUser'
```

### Webhook Forwarding

If you want to forward webhook events to your own endpoints:

1. Create webhook endpoints in the admin interface (`/admin/wallet/webhookendpoint/`)
2. Configure the endpoint URL, secret, and event types

### Transaction Fees

To configure transaction fees:

```python
WALLET_TRANSACTION_CHARGE_PERCENT = 1.5  # 1.5% charge on transactions
```

### Customizing Templates

To customize the admin templates, create the following directory structure in your project:

```
templates/
└── admin/
    └── wallet/
        └── analytics/
            ├── wallet_analytics.html
            ├── transaction_analytics.html
            └── settlement_analytics.html
```

Copy the original templates from the package and modify them as needed.

## Troubleshooting

### Webhook Issues

If webhooks are not being processed:

1. Check that your webhook URL is accessible from the internet
2. Verify that the webhook signature header is being sent correctly
3. Check the webhook events in the admin interface

### Transaction Issues

If transactions are failing:

1. Verify your Paystack API keys are correct
2. Check the transaction logs in the admin interface
3. Make sure your Paystack account is properly set up

### Database Issues

If you encounter database-related issues:

1. Make sure you've run migrations (`python manage.py migrate`)
2. Check that your database settings are correct
3. For production, use PostgreSQL or MySQL instead of SQLite

## Next Steps

After installation, see the [Configuration](configuration.md) and [Usage](usage.md) guides for more details on how to use and customize the wallet system.