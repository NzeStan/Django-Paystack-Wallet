# Django Paystack Wallet

A sophisticated Django wallet system integrated with Paystack payment gateway.

## Features

- 💰 **Wallet Management**: Create and manage digital wallets for users
- 💳 **Payment Processing**: Deposit funds using Paystack payment gateway
- 🏦 **Bank Transfers**: Withdraw funds to bank accounts
- 👥 **Peer Transfers**: Transfer funds between wallets
- 📊 **Transaction History**: Track all financial activities
- 💼 **Virtual Accounts**: Dedicated virtual accounts via Paystack
- 📱 **Card Management**: Save and charge cards for future payments
- 🏦 **Bank Account Management**: Add and verify bank accounts
- 🔄 **Settlements**: Automated wallet funds settlement to bank accounts
- 🔔 **Webhooks**: Process Paystack webhooks and forward to custom endpoints
- 📊 **Admin Dashboard**: Rich admin interface with analytics and exports
- 🌐 **REST API**: Complete API for all wallet operations
- 🔒 **Secure**: Built with security best practices
- 📋 **Comprehensive Logging**: Detailed logs for all operations
- 🌍 **Internationalization**: Built-in translation support

## Installation

```bash
pip install django-paystack-wallet
```

## Quick Start

1. Add `wallet` to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'wallet',
    'rest_framework',
]
```

2. Configure your Paystack API keys:

```python
# Paystack Configuration
PAYSTACK_SECRET_KEY = 'sk_test_your_secret_key'
PAYSTACK_PUBLIC_KEY = 'pk_test_your_public_key'
```

3. Run migrations:

```bash
python manage.py migrate
```

4. Include wallet URLs in your project's `urls.py`:

```python
urlpatterns = [
    ...
    path('wallet/', include('wallet.urls')),
]
```

5. Configure your webhook URL in Paystack dashboard:
   - Go to Paystack dashboard > Settings > API Keys & Webhooks
   - Add webhook URL: `https://your-domain.com/wallet/webhook/`

## Settings

The wallet system can be customized using the following settings in your `settings.py`:

```python
# Wallet Settings
WALLET_USE_UUID = True  # Use UUID instead of ID as primary key
WALLET_CURRENCY = 'NGN'  # Default currency
WALLET_AUTO_CREATE_WALLET = True  # Auto-create wallet for new users
WALLET_TRANSACTION_CHARGE_PERCENT = 1.5  # Default transaction charge
WALLET_MINIMUM_BALANCE = 0  # Minimum balance to maintain
WALLET_MAXIMUM_DAILY_TRANSACTION = 1000000  # Maximum daily transaction limit
WALLET_AUTO_SETTLEMENT = False  # Auto-settlement of wallet funds
```

## Usage Examples

### Creating a wallet

Wallets are automatically created for new users when `WALLET_AUTO_CREATE_WALLET = True`. You can also create a wallet manually:

```python
from wallet.services.wallet_service import WalletService

wallet_service = WalletService()
wallet = wallet_service.get_wallet(user)
```

### Deposit funds

```python
# Initialize a card charge
charge_data = wallet_service.initialize_card_charge(
    wallet=wallet,
    amount=1000.00,
    email=user.email
)

# Get authorization URL from charge_data
auth_url = charge_data.get('authorization_url')
# Redirect user to auth_url to complete payment
```

### Transfer between wallets

```python
# Transfer funds between wallets
wallet_service.transfer(
    source_wallet=source_wallet,
    destination_wallet=destination_wallet,
    amount=500.00,
    description="Transfer to friend"
)
```

### Withdraw to bank

```python
# Add a bank account
bank_account = wallet_service.add_bank_account(
    wallet=wallet,
    bank_code="058",  # GTBank code
    account_number="0123456789",
    account_name="John Doe"
)

# Withdraw to bank account
transaction, transfer_data = wallet_service.withdraw_to_bank(
    wallet=wallet,
    amount=2000.00,
    bank_account=bank_account,
    reason="Withdrawal to my account"
)
```

## API Endpoints

The wallet system provides a comprehensive REST API:

- `/api/wallets/` - Wallet operations
- `/api/transactions/` - Transaction operations
- `/api/cards/` - Card operations
- `/api/bank-accounts/` - Bank account operations
- `/api/banks/` - Bank list operations
- `/api/settlements/` - Settlement operations
- `/api/settlement-schedules/` - Settlement schedule operations
- `/webhook/` - Paystack webhook endpoint

Detailed API documentation is available in the `docs/` directory.

## Admin Interface

The wallet system provides a rich admin interface with:

- Dashboard with wallet analytics
- Transaction monitoring
- Card management
- Bank account verification
- Settlement processing
- Webhook event handling
- Export functionality (CSV, Excel, PDF)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.