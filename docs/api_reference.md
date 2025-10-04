# API Reference

This document provides comprehensive documentation for all the API endpoints available in the Django Paystack Wallet system.

## Authentication

All API endpoints require authentication. The wallet system uses Django REST Framework's authentication classes, which can be configured in your project settings.

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}
```

For token-based authentication, include the token in the request header:

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

## Base URL

All API endpoints are prefixed with `/wallet/api/` by default. This can be customized in your URL configuration.

## Wallet API

### List Wallets

Retrieves all wallets belonging to the authenticated user.

**Endpoint:** `GET /wallet/api/wallets/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "user": 1,
        "user_email": "user@example.com",
        "user_name": "John Doe",
        "balance_amount": "1000.00",
        "balance_currency": "NGN",
        "tag": "johndoe",
        "is_active": true,
        "is_locked": false,
        "last_transaction_date": "2023-01-15T12:30:45Z",
        "daily_transaction_total_amount": "500.00",
        "daily_transaction_count": 3,
        "daily_transaction_reset": "2023-01-15",
        "created_at": "2023-01-01T10:00:00Z",
        "updated_at": "2023-01-15T12:30:45Z",
        "dedicated_account_number": "0123456789",
        "dedicated_account_bank": "Test Bank"
    }
]
```

### Get Wallet

Retrieves a specific wallet by ID.

**Endpoint:** `GET /wallet/api/wallets/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "user": 1,
    "user_email": "user@example.com",
    "user_name": "John Doe",
    "balance_amount": "1000.00",
    "balance_currency": "NGN",
    "tag": "johndoe",
    "is_active": true,
    "is_locked": false,
    "last_transaction_date": "2023-01-15T12:30:45Z",
    "daily_transaction_total_amount": "500.00",
    "daily_transaction_count": 3,
    "daily_transaction_reset": "2023-01-15",
    "created_at": "2023-01-01T10:00:00Z",
    "updated_at": "2023-01-15T12:30:45Z",
    "dedicated_account_number": "0123456789",
    "dedicated_account_bank": "Test Bank",
    "transaction_count": 15,
    "cards_count": 2,
    "bank_accounts_count": 1,
    "paystack_customer_code": "CUS_123456"
}
```

You can also use `default` as the ID to retrieve the user's default wallet:

**Endpoint:** `GET /wallet/api/wallets/default/`

### Update Wallet

Updates a wallet's attributes.

**Endpoint:** `PATCH /wallet/api/wallets/{id}/`

**Request:**
```json
{
    "tag": "new-tag",
    "is_active": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "tag": "new-tag",
    "is_active": true,
    "is_locked": false
}
```

### Get Wallet Balance

Retrieves the current balance of a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/balance/`

**Response:**
```json
{
    "balance": "1000.00",
    "currency": "NGN"
}
```

### Deposit to Wallet

Initiates a deposit to the wallet using Paystack.

**Endpoint:** `POST /wallet/api/wallets/{id}/deposit/`

**Request:**
```json
{
    "amount": "500.00",
    "email": "user@example.com",
    "callback_url": "https://example.com/callback"
}
```

**Response:**
```json
{
    "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
    "access_code": "0peioxfhpn",
    "reference": "REF123456"
}
```

### Withdraw from Wallet

Withdraws funds from the wallet to a bank account.

**Endpoint:** `POST /wallet/api/wallets/{id}/withdraw/`

**Request:**
```json
{
    "amount": "200.00",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440001",
    "description": "Withdrawal to my account"
}
```

**Response:**
```json
{
    "transaction": {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "reference": "TRX123456",
        "amount_value": "200.00",
        "transaction_type": "withdrawal",
        "status": "success",
        "description": "Withdrawal to my account",
        "created_at": "2023-01-15T14:30:00Z"
    },
    "transfer_data": {
        "transfer_code": "TRF_123456",
        "status": "success"
    }
}
```

### Transfer to Another Wallet

Transfers funds from one wallet to another.

**Endpoint:** `POST /wallet/api/wallets/{id}/transfer/`

**Request:**
```json
{
    "amount": "100.00",
    "destination_wallet_id": "550e8400-e29b-41d4-a716-446655440003",
    "description": "Payment for services"
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440004",
    "reference": "TRX789012",
    "amount_value": "100.00",
    "amount_currency": "NGN",
    "transaction_type": "transfer",
    "transaction_type_display": "Transfer",
    "status": "success",
    "status_display": "Success",
    "description": "Payment for services",
    "recipient_wallet_id": "550e8400-e29b-41d4-a716-446655440003",
    "created_at": "2023-01-15T15:00:00Z"
}
```

### Lock Wallet

Locks a wallet to prevent transactions.

**Endpoint:** `POST /wallet/api/wallets/{id}/lock/`

**Response:**
```json
{
    "detail": "Wallet locked successfully"
}
```

### Unlock Wallet

Unlocks a previously locked wallet.

**Endpoint:** `POST /wallet/api/wallets/{id}/unlock/`

**Response:**
```json
{
    "detail": "Wallet unlocked successfully"
}
```

### Get Wallet Transactions

Retrieves transactions for a specific wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/transactions/?type=deposit&status=success&limit=10&offset=0`

**Parameters:**
- `type` (optional): Filter by transaction type (deposit, withdrawal, transfer, etc.)
- `status` (optional): Filter by transaction status (pending, success, failed, etc.)
- `limit` (optional): Number of results to return (default: 20)
- `offset` (optional): Result offset for pagination (default: 0)

**Response:**
```json
{
    "count": 15,
    "next": 10,
    "previous": null,
    "results": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440005",
            "reference": "TRX123456",
            "amount_value": "500.00",
            "amount_currency": "NGN",
            "transaction_type": "deposit",
            "transaction_type_display": "Deposit",
            "status": "success",
            "status_display": "Success",
            "description": "Deposit to wallet",
            "created_at": "2023-01-15T12:30:45Z",
            "completed_at": "2023-01-15T12:31:00Z"
        },
        // ...more transactions
    ]
}
```

### Get Wallet Cards

Retrieves all cards associated with a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/cards/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440006",
        "card_type": "visa",
        "card_type_display": "Visa",
        "last_four": "4242",
        "expiry_month": "12",
        "expiry_year": "2025",
        "is_default": true,
        "is_active": true,
        "is_expired": false,
        "masked_pan": "424242******4242",
        "created_at": "2023-01-10T10:00:00Z"
    }
]
```

### Get Wallet Bank Accounts

Retrieves all bank accounts associated with a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/bank_accounts/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440007",
        "bank_name": "Test Bank",
        "bank_code": "123",
        "account_number": "0123456789",
        "account_name": "John Doe",
        "account_type": "savings",
        "account_type_display": "Savings",
        "is_default": true,
        "is_active": true,
        "is_verified": true,
        "created_at": "2023-01-05T14:00:00Z"
    }
]
```

### Get Dedicated Account

Retrieves or creates a dedicated virtual account for a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/dedicated_account/`

**Response:**
```json
{
    "account_number": "0123456789",
    "bank_name": "Test Bank",
    "account_name": "John Doe"
}
```

## Transaction API

### List Transactions

Retrieves all transactions associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/transactions/?wallet_id=550e8400-e29b-41d4-a716-446655440000&transaction_type=deposit&status=success&limit=10&offset=0`

**Parameters:**
- `wallet_id` (optional): Filter by wallet ID
- `transaction_type` (optional): Filter by transaction type
- `status` (optional): Filter by status
- `reference` (optional): Filter by reference
- `start_date` (optional): Filter by start date (YYYY-MM-DD)
- `end_date` (optional): Filter by end date (YYYY-MM-DD)
- `min_amount` (optional): Filter by minimum amount
- `max_amount` (optional): Filter by maximum amount
- `payment_method` (optional): Filter by payment method
- `limit` (optional): Number of results (default: 20)
- `offset` (optional): Result offset for pagination (default: 0)

**Response:**
```json
{
    "count": 25,
    "next": 10,
    "previous": null,
    "results": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440008",
            "reference": "TRX123456",
            "amount_value": "500.00",
            "amount_currency": "NGN",
            "transaction_type": "deposit",
            "transaction_type_display": "Deposit",
            "status": "success",
            "status_display": "Success",
            "description": "Deposit to wallet",
            "created_at": "2023-01-15T12:30:45Z",
            "completed_at": "2023-01-15T12:31:00Z"
        },
        // ...more transactions
    ]
}
```

### Get Transaction

Retrieves a specific transaction by ID.

**Endpoint:** `GET /wallet/api/transactions/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440008",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount_value": "500.00",
    "amount_currency": "NGN",
    "reference": "TRX123456",
    "transaction_type": "deposit",
    "transaction_type_display": "Deposit",
    "status": "success",
    "status_display": "Success",
    "payment_method": "card",
    "payment_method_display": "Card",
    "description": "Deposit to wallet",
    "metadata": {},
    "recipient_wallet_id": null,
    "recipient_bank_account_id": null,
    "card_id": "550e8400-e29b-41d4-a716-446655440006",
    "related_transaction_id": null,
    "fees_value": "7.50",
    "ip_address": "127.0.0.1",
    "created_at": "2023-01-15T12:30:45Z",
    "updated_at": "2023-01-15T12:31:00Z",
    "completed_at": "2023-01-15T12:31:00Z",
    "failed_reason": null,
    "paystack_reference": "PSK_123456",
    "paystack_response": {}
}
```

### Verify Transaction

Verifies a transaction by reference.

**Endpoint:** `POST /wallet/api/transactions/verify/`

**Request:**
```json
{
    "reference": "TRX123456"
}
```

**Response:**
```json
{
    "status": "success",
    "reference": "TRX123456",
    "amount": 50000,
    "currency": "NGN",
    "customer": {
        "email": "user@example.com"
    }
}
```

### Refund Transaction

Creates a refund for a transaction.

**Endpoint:** `POST /wallet/api/transactions/refund/`

**Request:**
```json
{
    "transaction_id": "550e8400-e29b-41d4-a716-446655440008",
    "amount": "500.00",
    "reason": "Customer requested refund"
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440009",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount_value": "500.00",
    "amount_currency": "NGN",
    "reference": "TRX987654",
    "transaction_type": "refund",
    "transaction_type_display": "Refund",
    "status": "success",
    "status_display": "Success",
    "description": "Refund for transaction TRX123456",
    "related_transaction_id": "550e8400-e29b-41d4-a716-446655440008",
    "created_at": "2023-01-16T09:00:00Z",
    "completed_at": "2023-01-16T09:00:15Z"
}
```

## Card API

### List Cards

Retrieves all cards associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/cards/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440006",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "card_type": "visa",
        "card_type_display": "Visa",
        "last_four": "4242",
        "expiry_month": "12",
        "expiry_year": "2025",
        "bin": "424242",
        "card_holder_name": "John Doe",
        "email": "user@example.com",
        "is_default": true,
        "is_active": true,
        "is_expired": false,
        "masked_pan": "424242******4242",
        "created_at": "2023-01-10T10:00:00Z",
        "updated_at": "2023-01-10T10:00:00Z"
    }
]
```

### Get Card

Retrieves a specific card by ID.

**Endpoint:** `GET /wallet/api/cards/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440006",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "card_type": "visa",
    "card_type_display": "Visa",
    "last_four": "4242",
    "expiry_month": "12",
    "expiry_year": "2025",
    "bin": "424242",
    "card_holder_name": "John Doe",
    "email": "user@example.com",
    "is_default": true,
    "is_active": true,
    "is_expired": false,
    "masked_pan": "424242******4242",
    "created_at": "2023-01-10T10:00:00Z",
    "updated_at": "2023-01-10T10:00:00Z",
    "transaction_count": 5
}
```

### Update Card

Updates a card's attributes.

**Endpoint:** `PATCH /wallet/api/cards/{id}/`

**Request:**
```json
{
    "card_holder_name": "John Smith",
    "is_default": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440006",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "card_type": "visa",
    "card_type_display": "Visa",
    "last_four": "4242",
    "expiry_month": "12",
    "expiry_year": "2025",
    "bin": "424242",
    "card_holder_name": "John Smith",
    "email": "user@example.com",
    "is_default": true,
    "is_active": true,
    "is_expired": false,
    "masked_pan": "424242******4242",
    "created_at": "2023-01-10T10:00:00Z",
    "updated_at": "2023-01-16T14:30:00Z"
}
```

### Delete Card

Removes a card (marks it as inactive).

**Endpoint:** `DELETE /wallet/api/cards/{id}/`

**Response:** HTTP 204 No Content

### Charge Card

Charges a saved card.

**Endpoint:** `POST /wallet/api/cards/{id}/charge/`

**Request:**
```json
{
    "amount": "300.00",
    "description": "Charge for subscription"
}
```

**Response:**
```json
{
    "status": "success",
    "reference": "CHG_123456",
    "amount": 30000,
    "currency": "NGN",
    "customer": {
        "email": "user@example.com"
    }
}
```

### Initialize Card Payment

Initializes a new card payment.

**Endpoint:** `POST /wallet/api/cards/initialize/`

**Request:**
```json
{
    "amount": "500.00",
    "email": "user@example.com",
    "callback_url": "https://example.com/callback"
}
```

**Response:**
```json
{
    "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
    "access_code": "0peioxfhpn",
    "reference": "REF123456"
}
```

### Set Card as Default

Sets a card as the default payment method.

**Endpoint:** `POST /wallet/api/cards/{id}/set_default/`

**Response:**
```json
{
    "detail": "Card set as default successfully"
}
```

## Bank Account API

### List Bank Accounts

Retrieves all bank accounts associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/bank-accounts/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440007",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "bank_name": "Test Bank",
        "bank_code": "123",
        "account_number": "0123456789",
        "account_name": "John Doe",
        "account_type": "savings",
        "account_type_display": "Savings",
        "is_verified": true,
        "is_default": true,
        "is_active": true,
        "created_at": "2023-01-05T14:00:00Z",
        "updated_at": "2023-01-05T14:00:00Z"
    }
]
```

### Get Bank Account

Retrieves a specific bank account by ID.

**Endpoint:** `GET /wallet/api/bank-accounts/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440007",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_name": "Test Bank",
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "account_type": "savings",
    "account_type_display": "Savings",
    "is_verified": true,
    "is_default": true,
    "is_active": true,
    "created_at": "2023-01-05T14:00:00Z",
    "updated_at": "2023-01-05T14:00:00Z",
    "transaction_count": 3,
    "settlement_count": 1,
    "bank_details": {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    }
}
```

### Create Bank Account

Creates a new bank account.

**Endpoint:** `POST /wallet/api/bank-accounts/`

**Request:**
```json
{
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "account_type": "savings",
    "is_default": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440011",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_name": "Test Bank",
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "account_type": "savings",
    "account_type_display": "Savings",
    "is_verified": true,
    "is_default": true,
    "is_active": true,
    "created_at": "2023-01-16T15:00:00Z",
    "updated_at": "2023-01-16T15:00:00Z",
    "transaction_count": 0,
    "settlement_count": 0,
    "bank_details": {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    }
}
```

### Update Bank Account

Updates a bank account's attributes.

**Endpoint:** `PATCH /wallet/api/bank-accounts/{id}/`

**Request:**
```json
{
    "account_name": "John Smith",
    "is_default": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440007",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_name": "Test Bank",
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Smith",
    "account_type": "savings",
    "account_type_display": "Savings",
    "is_verified": true,
    "is_default": true,
    "is_active": true,
    "created_at": "2023-01-05T14:00:00Z",
    "updated_at": "2023-01-16T15:30:00Z"
}
```

### Delete Bank Account

Removes a bank account (marks it as inactive).

**Endpoint:** `DELETE /wallet/api/bank-accounts/{id}/`

**Response:** HTTP 204 No Content

### Verify Bank Account

Verifies a bank account with Paystack.

**Endpoint:** `POST /wallet/api/bank-accounts/verify/`

**Request:**
```json
{
    "account_number": "0123456789",
    "bank_code": "123"
}
```

**Response:**
```json
{
    "account_number": "0123456789",
    "account_name": "John Doe",
    "bank_code": "123"
}
```

### Set Bank Account as Default

Sets a bank account as the default for withdrawals.

**Endpoint:** `POST /wallet/api/bank-accounts/{id}/set_default/`

**Response:**
```json
{
    "detail": "Bank account set as default successfully"
}
```

## Bank API

### List Banks

Retrieves all available banks.

**Endpoint:** `GET /wallet/api/banks/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440012",
        "name": "Another Bank",
        "code": "456",
        "slug": "another-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    }
]
```

### Get Bank

Retrieves a specific bank by ID.

**Endpoint:** `GET /wallet/api/banks/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440010",
    "name": "Test Bank",
    "code": "123",
    "slug": "test-bank",
    "country": "NG",
    "currency": "NGN",
    "type": "nuban",
    "is_active": true
}
```

### Refresh Banks

Refreshes the bank list from Paystack.

**Endpoint:** `GET /wallet/api/banks/refresh/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    },
    // ...more banks
]
```

## Settlement API

### List Settlements

Retrieves all settlements associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/settlements/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440013",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
        "bank_account_name": "John Doe",
        "bank_account_number": "0123456789",
        "bank_name": "Test Bank",
        "amount_value": "1000.00",
        "amount_currency": "NGN",
        "fees_value": "10.00",
        "status": "success",
        "status_display": "Success",
        "reference": "STL123456",
        "paystack_transfer_code": "TRF_123456",
        "reason": "Monthly settlement",
        "metadata": {},
        "transaction_id": "550e8400-e29b-41d4-a716-446655440014",
        "created_at": "2023-01-15T00:00:00Z",
        "updated_at": "2023-01-15T00:05:00Z",
        "settled_at": "2023-01-15T00:05:00Z",
        "failure_reason": null
    }
]
```

### Get Settlement

Retrieves a specific settlement by ID.

**Endpoint:** `GET /wallet/api/settlements/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440013",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "bank_account_name": "John Doe",
    "bank_account_number": "0123456789",
    "bank_name": "Test Bank",
    "amount_value": "1000.00",
    "amount_currency": "NGN",
    "fees_value": "10.00",
    "status": "success",
    "status_display": "Success",
    "reference": "STL123456",
    "paystack_transfer_code": "TRF_123456",
    "reason": "Monthly settlement",
    "metadata": {},
    "transaction_id": "550e8400-e29b-41d4-a716-446655440014",
    "created_at": "2023-01-15T00:00:00Z",
    "updated_at": "2023-01-15T00:05:00Z",
    "settled_at": "2023-01-15T00:05:00Z",
    "failure_reason": null,
    "paystack_transfer_data": {
        "amount": 100000,
        "status": "success",
        "transfer_code": "TRF_123456",
        "recipient": {
            "recipient_code": "RCP_123456",
            "name": "John Doe",
            "type": "nuban"
        }
    }
}
```

### Create Settlement

Creates a new settlement to transfer funds to a bank account.

**Endpoint:** `POST /wallet/api/settlements/create_settlement/`

**Request:**
```json
{
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "amount": "500.00",
    "reason": "Manual settlement"
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440015",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "bank_account_name": "John Doe",
    "bank_account_number": "0123456789",
    "bank_name": "Test Bank",
    "amount_value": "500.00",
    "amount_currency": "NGN",
    "fees_value": "5.00",
    "status": "pending",
    "status_display": "Pending",
    "reference": "STL987654",
    "paystack_transfer_code": "TRF_987654",
    "reason": "Manual settlement",
    "metadata": {},
    "transaction_id": "550e8400-e29b-41d4-a716-446655440016",
    "created_at": "2023-01-16T15:00:00Z",
    "updated_at": "2023-01-16T15:00:00Z",
    "settled_at": null,
    "failure_reason": null
}
```

### Verify Settlement

Verifies the status of a settlement with Paystack.

**Endpoint:** `POST /wallet/api/settlements/{id}/verify/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440015",
    "status": "success",
    "status_display": "Success",
    "settled_at": "2023-01-16T15:05:00Z",
    "paystack_transfer_data": {
        "amount": 50000,
        "status": "success",
        "transfer_code": "TRF_987654",
        "recipient": {
            "recipient_code": "RCP_123456",
            "name": "John Doe",
            "type": "nuban"
        }
    }
}
```

## Settlement Schedule API

### List Settlement Schedules

Retrieves all settlement schedules associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/settlement-schedules/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440017",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
        "bank_account_name": "John Doe",
        "bank_account_number": "0123456789",
        "bank_name": "Test Bank",
        "is_active": true,
        "schedule_type": "monthly",
        "schedule_type_display": "Monthly",
        "amount_threshold_value": null,
        "minimum_amount_value": "100.00",
        "maximum_amount_value": "1000.00",
        "day_of_week": null,
        "day_of_week_display": null,
        "day_of_month": 15,
        "time_of_day": "00:00:00",
        "last_settlement": "2023-01-15T00:00:00Z",
        "next_settlement": "2023-02-15T00:00:00Z",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2023-01-15T00:05:00Z"
    }
]
```

### Get Settlement Schedule

Retrieves a specific settlement schedule by ID.

**Endpoint:** `GET /wallet/api/settlement-schedules/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440017",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "bank_account_name": "John Doe",
    "bank_account_number": "0123456789",
    "bank_name": "Test Bank",
    "is_active": true,
    "schedule_type": "monthly",
    "schedule_type_display": "Monthly",
    "amount_threshold_value": null,
    "minimum_amount_value": "100.00",
    "maximum_amount_value": "1000.00",
    "day_of_week": null,
    "day_of_week_display": null,
    "day_of_month": 15,
    "time_of_day": "00:00:00",
    "last_settlement": "2023-01-15T00:00:00Z",
    "next_settlement": "2023-02-15T00:00:00Z",
    "created_at": "2023-01-01T00:00:00Z",
    "updated_at": "2023-01-15T00:05:00Z"
}
```

### Create Settlement Schedule

Creates a new settlement schedule.

**Endpoint:** `POST /wallet/api/settlement-schedules/`

**Request:**
```json
{
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "schedule_type": "weekly",
    "minimum_amount": "100.00",
    "maximum_amount": "1000.00",
    "day_of_week": 1,
    "time_of_day": "12:00:00",
    "is_active": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440018",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "bank_account_name": "John Doe",
    "bank_account_number": "0123456789",
    "bank_name": "Test Bank",
    "is_active": true,
    "schedule_type": "weekly",
    "schedule_type_display": "Weekly",
    "amount_threshold_value": null,
    "minimum_amount_value": "100.00",
    "maximum_amount_value": "1000.00",
    "day_of_week": 1,
    "day_of_week_display": "Tuesday",
    "day_of_month": null,
    "time_of_day": "12:00:00",
    "last_settlement": null,
    "next_settlement": "2023-01-17T12:00:00Z",
    "created_at": "2023-01-16T15:00:00Z",
    "updated_at": "2023-01-16T15:00:00Z"
}
```

### Update Settlement Schedule

Updates a settlement schedule's attributes.

**Endpoint:** `PATCH /wallet/api/settlement-schedules/{id}/`

**Request:**
```json
{
    "is_active": false,
    "minimum_amount": "200.00"
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440017",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "bank_account_name": "John Doe",
    "bank_account_number": "0123456789",
    "bank_name": "Test Bank",
    "is_active": false,
    "schedule_type": "monthly",
    "schedule_type_display": "Monthly",
    "amount_threshold_value": null,
    "minimum_amount_value": "200.00",
    "maximum_amount_value": "1000.00",
    "day_of_week": null,
    "day_of_week_display": null,
    "day_of_month": 15,
    "time_of_day": "00:00:00",
    "last_settlement": "2023-01-15T00:00:00Z",
    "next_settlement": "2023-02-15T00:00:00Z",
    "created_at": "2023-01-01T00:00:00Z",
    "updated_at": "2023-01-16T15:30:00Z"
}
```

### Delete Settlement Schedule

Deletes a settlement schedule.

**Endpoint:** `DELETE /wallet/api/settlement-schedules/{id}/`

**Response:** HTTP 204 No Content

### Recalculate Next Settlement

Recalculates the next settlement date for a schedule.

**Endpoint:** `POST /wallet/api/settlement-schedules/{id}/recalculate/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440017",
    "next_settlement": "2023-02-15T00:00:00Z"
}
```

## Webhook API

### Paystack Webhook

Processes webhook events from Paystack.

**Endpoint:** `POST /wallet/webhook/`

**Headers:**
```
X-Paystack-Signature: a4a51e39c76a7b55b4791245d5cd391dd7a51e32
Content-Type: application/json
```

**Request:**
```json
{
    "event": "charge.success",
    "data": {
        "id": 123456,
        "status": "success",
        "reference": "REF123456",
        "amount": 50000,
        "currency": "NGN",
        "channel": "card",
        "customer": {
            "id": 87654,
            "email": "user@example.com"
        },
        "authorization": {
            "authorization_code": "AUTH_123456",
            "card_type": "visa",
            "last4": "4242",
            "exp_month": "12",
            "exp_year": "2025",
            "bin": "424242",
            "bank": "Test Bank",
            "reusable": true
        },
        "metadata": {
            "wallet_id": "550e8400-e29b-41d4-a716-446655440000"
        }
    }
}
```

**Response:**
```json
{
    "status": "success",
    "event_id": "550e8400-e29b-41d4-a716-446655440019"
}
```

## Error Responses

### Authentication Error

**Response:** HTTP 401 Unauthorized
```json
{
    "detail": "Authentication credentials were not provided."
}
```

### Permission Error

**Response:** HTTP 403 Forbidden
```json
{
    "detail": "You do not have permission to perform this action."
}
```

### Not Found Error

**Response:** HTTP 404 Not Found
```json
{
    "detail": "Not found."
}
```

### Validation Error

**Response:** HTTP 400 Bad Request
```json
{
    "amount": [
        "Ensure this value is greater than or equal to 0.01."
    ],
    "bank_account_id": [
        "Bank account not found."
    ]
}
```

### Business Logic Error

**Response:** HTTP 400 Bad Request
```json
{
    "detail": "Insufficient funds in wallet."
}
```

## Pagination

All list endpoints support pagination using the `limit` and `offset` query parameters:

```
GET /wallet/api/transactions/?limit=10&offset=20
```

The response includes pagination information:

```json
{
    "count": 35,
    "next": 30,
    "previous": 10,
    "results": [
        // Items
    ]
}
```

## Filtering

Many endpoints support filtering using query parameters:

```
GET /wallet/api/transactions/?transaction_type=deposit&status=success
```

Refer to the individual endpoint documentation for available filters.

## Cross-Origin Resource Sharing (CORS)

The API supports CORS for cross-domain requests. The following headers are included in responses:

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

If you need to restrict CORS to specific domains, you can configure it in your Django settings:

```python
CORS_ALLOWED_ORIGINS = [
    "https://example.com",
    "https://app.example.com"
]
```

## API Versioning

API versioning is not implemented by default but can be added if needed. If you want to implement versioning, you can use Django REST Framework's versioning classes:

```python
REST_FRAMEWORK = {
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ['v1'],
    'VERSION_PARAM': 'version',
}
```

Then, URLs would be structured as:

```
/wallet/api/v1/wallets/
```

## Rate Limiting

Rate limiting is not implemented by default but can be added if needed. If you want to implement rate limiting, you can use Django REST Framework's throttling classes:

```python
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day'
    }
}
```

## Next Steps

This concludes the API reference documentation. For implementation details, see the [Installation Guide](installation.md), [Configuration Guide](configuration.md), and [Usage Guide](usage.md).# API Reference

This document provides comprehensive documentation for all the API endpoints available in the Django Paystack Wallet system.

## Authentication

All API endpoints require authentication. The wallet system uses Django REST Framework's authentication classes, which can be configured in your project settings.

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}
```

For token-based authentication, include the token in the request header:

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

## Base URL

All API endpoints are prefixed with `/wallet/api/` by default. This can be customized in your URL configuration.

## Wallet API

### List Wallets

Retrieves all wallets belonging to the authenticated user.

**Endpoint:** `GET /wallet/api/wallets/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "user": 1,
        "user_email": "user@example.com",
        "user_name": "John Doe",
        "balance_amount": "1000.00",
        "balance_currency": "NGN",
        "tag": "johndoe",
        "is_active": true,
        "is_locked": false,
        "last_transaction_date": "2023-01-15T12:30:45Z",
        "daily_transaction_total_amount": "500.00",
        "daily_transaction_count": 3,
        "daily_transaction_reset": "2023-01-15",
        "created_at": "2023-01-01T10:00:00Z",
        "updated_at": "2023-01-15T12:30:45Z",
        "dedicated_account_number": "0123456789",
        "dedicated_account_bank": "Test Bank"
    }
]
```

### Get Wallet

Retrieves a specific wallet by ID.

**Endpoint:** `GET /wallet/api/wallets/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "user": 1,
    "user_email": "user@example.com",
    "user_name": "John Doe",
    "balance_amount": "1000.00",
    "balance_currency": "NGN",
    "tag": "johndoe",
    "is_active": true,
    "is_locked": false,
    "last_transaction_date": "2023-01-15T12:30:45Z",
    "daily_transaction_total_amount": "500.00",
    "daily_transaction_count": 3,
    "daily_transaction_reset": "2023-01-15",
    "created_at": "2023-01-01T10:00:00Z",
    "updated_at": "2023-01-15T12:30:45Z",
    "dedicated_account_number": "0123456789",
    "dedicated_account_bank": "Test Bank",
    "transaction_count": 15,
    "cards_count": 2,
    "bank_accounts_count": 1,
    "paystack_customer_code": "CUS_123456"
}
```

You can also use `default` as the ID to retrieve the user's default wallet:

**Endpoint:** `GET /wallet/api/wallets/default/`

### Update Wallet

Updates a wallet's attributes.

**Endpoint:** `PATCH /wallet/api/wallets/{id}/`

**Request:**
```json
{
    "tag": "new-tag",
    "is_active": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "tag": "new-tag",
    "is_active": true,
    "is_locked": false
}
```

### Get Wallet Balance

Retrieves the current balance of a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/balance/`

**Response:**
```json
{
    "balance": "1000.00",
    "currency": "NGN"
}
```

### Deposit to Wallet

Initiates a deposit to the wallet using Paystack.

**Endpoint:** `POST /wallet/api/wallets/{id}/deposit/`

**Request:**
```json
{
    "amount": "500.00",
    "email": "user@example.com",
    "callback_url": "https://example.com/callback"
}
```

**Response:**
```json
{
    "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
    "access_code": "0peioxfhpn",
    "reference": "REF123456"
}
```

### Withdraw from Wallet

Withdraws funds from the wallet to a bank account.

**Endpoint:** `POST /wallet/api/wallets/{id}/withdraw/`

**Request:**
```json
{
    "amount": "200.00",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440001",
    "description": "Withdrawal to my account"
}
```

**Response:**
```json
{
    "transaction": {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "reference": "TRX123456",
        "amount_value": "200.00",
        "transaction_type": "withdrawal",
        "status": "success",
        "description": "Withdrawal to my account",
        "created_at": "2023-01-15T14:30:00Z"
    },
    "transfer_data": {
        "transfer_code": "TRF_123456",
        "status": "success"
    }
}
```

### Transfer to Another Wallet

Transfers funds from one wallet to another.

**Endpoint:** `POST /wallet/api/wallets/{id}/transfer/`

**Request:**
```json
{
    "amount": "100.00",
    "destination_wallet_id": "550e8400-e29b-41d4-a716-446655440003",
    "description": "Payment for services"
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440004",
    "reference": "TRX789012",
    "amount_value": "100.00",
    "amount_currency": "NGN",
    "transaction_type": "transfer",
    "transaction_type_display": "Transfer",
    "status": "success",
    "status_display": "Success",
    "description": "Payment for services",
    "recipient_wallet_id": "550e8400-e29b-41d4-a716-446655440003",
    "created_at": "2023-01-15T15:00:00Z"
}
```

### Lock Wallet

Locks a wallet to prevent transactions.

**Endpoint:** `POST /wallet/api/wallets/{id}/lock/`

**Response:**
```json
{
    "detail": "Wallet locked successfully"
}
```

### Unlock Wallet

Unlocks a previously locked wallet.

**Endpoint:** `POST /wallet/api/wallets/{id}/unlock/`

**Response:**
```json
{
    "detail": "Wallet unlocked successfully"
}
```

### Get Wallet Transactions

Retrieves transactions for a specific wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/transactions/?type=deposit&status=success&limit=10&offset=0`

**Parameters:**
- `type` (optional): Filter by transaction type (deposit, withdrawal, transfer, etc.)
- `status` (optional): Filter by transaction status (pending, success, failed, etc.)
- `limit` (optional): Number of results to return (default: 20)
- `offset` (optional): Result offset for pagination (default: 0)

**Response:**
```json
{
    "count": 15,
    "next": 10,
    "previous": null,
    "results": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440005",
            "reference": "TRX123456",
            "amount_value": "500.00",
            "amount_currency": "NGN",
            "transaction_type": "deposit",
            "transaction_type_display": "Deposit",
            "status": "success",
            "status_display": "Success",
            "description": "Deposit to wallet",
            "created_at": "2023-01-15T12:30:45Z",
            "completed_at": "2023-01-15T12:31:00Z"
        },
        // ...more transactions
    ]
}
```

### Get Wallet Cards

Retrieves all cards associated with a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/cards/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440006",
        "card_type": "visa",
        "card_type_display": "Visa",
        "last_four": "4242",
        "expiry_month": "12",
        "expiry_year": "2025",
        "is_default": true,
        "is_active": true,
        "is_expired": false,
        "masked_pan": "424242******4242",
        "created_at": "2023-01-10T10:00:00Z"
    }
]
```

### Get Wallet Bank Accounts

Retrieves all bank accounts associated with a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/bank_accounts/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440007",
        "bank_name": "Test Bank",
        "bank_code": "123",
        "account_number": "0123456789",
        "account_name": "John Doe",
        "account_type": "savings",
        "account_type_display": "Savings",
        "is_default": true,
        "is_active": true,
        "is_verified": true,
        "created_at": "2023-01-05T14:00:00Z"
    }
]
```

### Get Dedicated Account

Retrieves or creates a dedicated virtual account for a wallet.

**Endpoint:** `GET /wallet/api/wallets/{id}/dedicated_account/`

**Response:**
```json
{
    "account_number": "0123456789",
    "bank_name": "Test Bank",
    "account_name": "John Doe"
}
```

## Transaction API

### List Transactions

Retrieves all transactions associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/transactions/?wallet_id=550e8400-e29b-41d4-a716-446655440000&transaction_type=deposit&status=success&limit=10&offset=0`

**Parameters:**
- `wallet_id` (optional): Filter by wallet ID
- `transaction_type` (optional): Filter by transaction type
- `status` (optional): Filter by status
- `reference` (optional): Filter by reference
- `start_date` (optional): Filter by start date (YYYY-MM-DD)
- `end_date` (optional): Filter by end date (YYYY-MM-DD)
- `min_amount` (optional): Filter by minimum amount
- `max_amount` (optional): Filter by maximum amount
- `payment_method` (optional): Filter by payment method
- `limit` (optional): Number of results (default: 20)
- `offset` (optional): Result offset for pagination (default: 0)

**Response:**
```json
{
    "count": 25,
    "next": 10,
    "previous": null,
    "results": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440008",
            "reference": "TRX123456",
            "amount_value": "500.00",
            "amount_currency": "NGN",
            "transaction_type": "deposit",
            "transaction_type_display": "Deposit",
            "status": "success",
            "status_display": "Success",
            "description": "Deposit to wallet",
            "created_at": "2023-01-15T12:30:45Z",
            "completed_at": "2023-01-15T12:31:00Z"
        },
        // ...more transactions
    ]
}
```

### Get Transaction

Retrieves a specific transaction by ID.

**Endpoint:** `GET /wallet/api/transactions/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440008",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount_value": "500.00",
    "amount_currency": "NGN",
    "reference": "TRX123456",
    "transaction_type": "deposit",
    "transaction_type_display": "Deposit",
    "status": "success",
    "status_display": "Success",
    "payment_method": "card",
    "payment_method_display": "Card",
    "description": "Deposit to wallet",
    "metadata": {},
    "recipient_wallet_id": null,
    "recipient_bank_account_id": null,
    "card_id": "550e8400-e29b-41d4-a716-446655440006",
    "related_transaction_id": null,
    "fees_value": "7.50",
    "ip_address": "127.0.0.1",
    "created_at": "2023-01-15T12:30:45Z",
    "updated_at": "2023-01-15T12:31:00Z",
    "completed_at": "2023-01-15T12:31:00Z",
    "failed_reason": null,
    "paystack_reference": "PSK_123456",
    "paystack_response": {}
}
```

### Verify Transaction

Verifies a transaction by reference.

**Endpoint:** `POST /wallet/api/transactions/verify/`

**Request:**
```json
{
    "reference": "TRX123456"
}
```

**Response:**
```json
{
    "status": "success",
    "reference": "TRX123456",
    "amount": 50000,
    "currency": "NGN",
    "customer": {
        "email": "user@example.com"
    }
}
```

### Refund Transaction

Creates a refund for a transaction.

**Endpoint:** `POST /wallet/api/transactions/refund/`

**Request:**
```json
{
    "transaction_id": "550e8400-e29b-41d4-a716-446655440008",
    "amount": "500.00",
    "reason": "Customer requested refund"
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440009",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount_value": "500.00",
    "amount_currency": "NGN",
    "reference": "TRX987654",
    "transaction_type": "refund",
    "transaction_type_display": "Refund",
    "status": "success",
    "status_display": "Success",
    "description": "Refund for transaction TRX123456",
    "related_transaction_id": "550e8400-e29b-41d4-a716-446655440008",
    "created_at": "2023-01-16T09:00:00Z",
    "completed_at": "2023-01-16T09:00:15Z"
}
```

## Card API

### List Cards

Retrieves all cards associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/cards/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440006",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "card_type": "visa",
        "card_type_display": "Visa",
        "last_four": "4242",
        "expiry_month": "12",
        "expiry_year": "2025",
        "bin": "424242",
        "card_holder_name": "John Doe",
        "email": "user@example.com",
        "is_default": true,
        "is_active": true,
        "is_expired": false,
        "masked_pan": "424242******4242",
        "created_at": "2023-01-10T10:00:00Z",
        "updated_at": "2023-01-10T10:00:00Z"
    }
]
```

### Get Card

Retrieves a specific card by ID.

**Endpoint:** `GET /wallet/api/cards/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440006",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "card_type": "visa",
    "card_type_display": "Visa",
    "last_four": "4242",
    "expiry_month": "12",
    "expiry_year": "2025",
    "bin": "424242",
    "card_holder_name": "John Doe",
    "email": "user@example.com",
    "is_default": true,
    "is_active": true,
    "is_expired": false,
    "masked_pan": "424242******4242",
    "created_at": "2023-01-10T10:00:00Z",
    "updated_at": "2023-01-10T10:00:00Z",
    "transaction_count": 5
}
```

### Update Card

Updates a card's attributes.

**Endpoint:** `PATCH /wallet/api/cards/{id}/`

**Request:**
```json
{
    "card_holder_name": "John Smith",
    "is_default": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440006",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "card_type": "visa",
    "card_type_display": "Visa",
    "last_four": "4242",
    "expiry_month": "12",
    "expiry_year": "2025",
    "bin": "424242",
    "card_holder_name": "John Smith",
    "email": "user@example.com",
    "is_default": true,
    "is_active": true,
    "is_expired": false,
    "masked_pan": "424242******4242",
    "created_at": "2023-01-10T10:00:00Z",
    "updated_at": "2023-01-16T14:30:00Z"
}
```

### Delete Card

Removes a card (marks it as inactive).

**Endpoint:** `DELETE /wallet/api/cards/{id}/`

**Response:** HTTP 204 No Content

### Charge Card

Charges a saved card.

**Endpoint:** `POST /wallet/api/cards/{id}/charge/`

**Request:**
```json
{
    "amount": "300.00",
    "description": "Charge for subscription"
}
```

**Response:**
```json
{
    "status": "success",
    "reference": "CHG_123456",
    "amount": 30000,
    "currency": "NGN",
    "customer": {
        "email": "user@example.com"
    }
}
```

### Initialize Card Payment

Initializes a new card payment.

**Endpoint:** `POST /wallet/api/cards/initialize/`

**Request:**
```json
{
    "amount": "500.00",
    "email": "user@example.com",
    "callback_url": "https://example.com/callback"
}
```

**Response:**
```json
{
    "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
    "access_code": "0peioxfhpn",
    "reference": "REF123456"
}
```

### Set Card as Default

Sets a card as the default payment method.

**Endpoint:** `POST /wallet/api/cards/{id}/set_default/`

**Response:**
```json
{
    "detail": "Card set as default successfully"
}
```

## Bank Account API

### List Bank Accounts

Retrieves all bank accounts associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/bank-accounts/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440007",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "bank_name": "Test Bank",
        "bank_code": "123",
        "account_number": "0123456789",
        "account_name": "John Doe",
        "account_type": "savings",
        "account_type_display": "Savings",
        "is_verified": true,
        "is_default": true,
        "is_active": true,
        "created_at": "2023-01-05T14:00:00Z",
        "updated_at": "2023-01-05T14:00:00Z"
    }
]
```

### Get Bank Account

Retrieves a specific bank account by ID.

**Endpoint:** `GET /wallet/api/bank-accounts/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440007",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_name": "Test Bank",
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "account_type": "savings",
    "account_type_display": "Savings",
    "is_verified": true,
    "is_default": true,
    "is_active": true,
    "created_at": "2023-01-05T14:00:00Z",
    "updated_at": "2023-01-05T14:00:00Z",
    "transaction_count": 3,
    "settlement_count": 1,
    "bank_details": {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    }
}
```

### Create Bank Account

Creates a new bank account.

**Endpoint:** `POST /wallet/api/bank-accounts/`

**Request:**
```json
{
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "account_type": "savings",
    "is_default": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440011",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_name": "Test Bank",
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "account_type": "savings",
    "account_type_display": "Savings",
    "is_verified": true,
    "is_default": true,
    "is_active": true,
    "created_at": "2023-01-16T15:00:00Z",
    "updated_at": "2023-01-16T15:00:00Z",
    "transaction_count": 0,
    "settlement_count": 0,
    "bank_details": {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    }
}
```

### Update Bank Account

Updates a bank account's attributes.

**Endpoint:** `PATCH /wallet/api/bank-accounts/{id}/`

**Request:**
```json
{
    "account_name": "John Smith",
    "is_default": true
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440007",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_name": "Test Bank",
    "bank_code": "123",
    "account_number": "0123456789",
    "account_name": "John Smith",
    "account_type": "savings",
    "account_type_display": "Savings",
    "is_verified": true,
    "is_default": true,
    "is_active": true,
    "created_at": "2023-01-05T14:00:00Z",
    "updated_at": "2023-01-16T15:30:00Z"
}
```

### Delete Bank Account

Removes a bank account (marks it as inactive).

**Endpoint:** `DELETE /wallet/api/bank-accounts/{id}/`

**Response:** HTTP 204 No Content

### Verify Bank Account

Verifies a bank account with Paystack.

**Endpoint:** `POST /wallet/api/bank-accounts/verify/`

**Request:**
```json
{
    "account_number": "0123456789",
    "bank_code": "123"
}
```

**Response:**
```json
{
    "account_number": "0123456789",
    "account_name": "John Doe",
    "bank_code": "123"
}
```

### Set Bank Account as Default

Sets a bank account as the default for withdrawals.

**Endpoint:** `POST /wallet/api/bank-accounts/{id}/set_default/`

**Response:**
```json
{
    "detail": "Bank account set as default successfully"
}
```

## Bank API

### List Banks

Retrieves all available banks.

**Endpoint:** `GET /wallet/api/banks/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440012",
        "name": "Another Bank",
        "code": "456",
        "slug": "another-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    }
]
```

### Get Bank

Retrieves a specific bank by ID.

**Endpoint:** `GET /wallet/api/banks/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440010",
    "name": "Test Bank",
    "code": "123",
    "slug": "test-bank",
    "country": "NG",
    "currency": "NGN",
    "type": "nuban",
    "is_active": true
}
```

### Refresh Banks

Refreshes the bank list from Paystack.

**Endpoint:** `GET /wallet/api/banks/refresh/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "name": "Test Bank",
        "code": "123",
        "slug": "test-bank",
        "country": "NG",
        "currency": "NGN",
        "type": "nuban",
        "is_active": true
    },
    // ...more banks
]
```

## Settlement API

### List Settlements

Retrieves all settlements associated with the authenticated user's wallets.

**Endpoint:** `GET /wallet/api/settlements/`

**Response:**
```json
[
    {
        "id": "550e8400-e29b-41d4-a716-446655440013",
        "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
        "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
        "bank_account_name": "John Doe",
        "bank_account_number": "0123456789",
        "bank_name": "Test Bank",
        "amount_value": "1000.00",
        "amount_currency": "NGN",
        "fees_value": "10.00",
        "status": "success",
        "status_display": "Success",
        "reference": "STL123456",
        "paystack_transfer_code": "TRF_123456",
        "reason": "Monthly settlement",
        "metadata": {},
        "transaction_id": "550e8400-e29b-41d4-a716-446655440014",
        "created_at": "2023-01-15T00:00:00Z",
        "updated_at": "2023-01-15T00:05:00Z",
        "settled_at": "2023-01-15T00:05:00Z",
        "failure_reason": null
    }
]
```

### Get Settlement

Retrieves a specific settlement by ID.

**Endpoint:** `GET /wallet/api/settlements/{id}/`

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440013",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "bank_account_id": "550e8400-e29b-41d4-a716-446655440007",
    "bank_account_name": "John Doe",
    "bank_account_number": "0123456789",
    "bank_name": "Test Bank",
    "amount_value": "1000.00",
    "amount_currency": "NGN",
    "fees_value": "10.00",