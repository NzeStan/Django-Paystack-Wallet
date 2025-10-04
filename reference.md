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