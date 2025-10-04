# Usage Guide

This guide provides examples and code snippets for using the Django Paystack Wallet system in your application.

## Working with Wallets

### Getting a User's Wallet

```python
from wallet.services.wallet_service import WalletService

def get_user_wallet(user):
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    return wallet
```

### Checking Wallet Balance

```python
def get_balance(user):
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    balance = wallet_service.get_balance(wallet)
    return balance
```

### Locking and Unlocking a Wallet

```python
def lock_wallet(user):
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    wallet.lock()
    return f"Wallet {wallet.id} locked"

def unlock_wallet(user):
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    wallet.unlock()
    return f"Wallet {wallet.id} unlocked"
```

## Handling Deposits

### Initializing a Card Charge

```python
from decimal import Decimal

def initiate_deposit(user, amount):
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    charge_data = wallet_service.initialize_card_charge(
        wallet=wallet,
        amount=Decimal(amount),
        email=user.email,
        callback_url="https://example.com/callback"
    )
    
    # Return the authorization URL for redirection
    return charge_data.get('authorization_url')
```

### Processing a Successful Charge

```python
def process_successful_charge(reference):
    wallet_service = WalletService()
    transaction_data = wallet_service.verify_card_charge(reference)
    
    if transaction_data.get('status') == 'success':
        wallet, transaction, card = wallet_service.process_successful_card_charge(transaction_data)
        return {
            'wallet_id': wallet.id,
            'transaction_id': transaction.id,
            'amount': transaction.amount,
            'status': transaction.status
        }
    else:
        return {'status': 'failed', 'reason': transaction_data.get('gateway_response')}
```

### Charging a Saved Card

```python
def charge_saved_card(user, card_id, amount):
    from wallet.models import Card
    
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        card = Card.objects.get(id=card_id, wallet=wallet)
        
        charge_data = wallet_service.charge_saved_card(
            card=card,
            amount=Decimal(amount)
        )
        
        return charge_data
    except Card.DoesNotExist:
        return {'status': 'failed', 'reason': 'Card not found'}
```

## Bank Account Operations

### Adding a Bank Account

```python
def add_bank_account(user, bank_code, account_number):
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        # Verify account first
        verification = wallet_service.verify_bank_account(account_number, bank_code)
        account_name = verification.get('account_name')
        
        # Add the verified account
        bank_account = wallet_service.add_bank_account(
            wallet=wallet,
            bank_code=bank_code,
            account_number=account_number,
            account_name=account_name
        )
        
        return {
            'id': bank_account.id,
            'account_name': bank_account.account_name,
            'account_number': bank_account.account_number,
            'bank_name': bank_account.bank.name
        }
    except Exception as e:
        return {'status': 'failed', 'reason': str(e)}
```

### Withdrawing to a Bank Account

```python
def withdraw_to_bank(user, bank_account_id, amount):
    from wallet.models import BankAccount
    from wallet.exceptions import InsufficientFunds
    
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, wallet=wallet)
        
        transaction, transfer_data = wallet_service.withdraw_to_bank(
            wallet=wallet,
            amount=Decimal(amount),
            bank_account=bank_account,
            reason="Withdrawal to bank account"
        )
        
        return {
            'transaction_id': transaction.id,
            'status': transaction.status,
            'amount': str(transaction.amount),
            'transfer_code': transfer_data.get('transfer_code')
        }
    except BankAccount.DoesNotExist:
        return {'status': 'failed', 'reason': 'Bank account not found'}
    except InsufficientFunds:
        return {'status': 'failed', 'reason': 'Insufficient funds'}
```

## Transfers Between Wallets

### Transferring Funds

```python
def transfer_funds(sender_user, recipient_id, amount, description=None):
    from wallet.models import Wallet
    from wallet.exceptions import InsufficientFunds, WalletLocked
    
    wallet_service = WalletService()
    sender_wallet = wallet_service.get_wallet(sender_user)
    
    try:
        recipient_wallet = Wallet.objects.get(id=recipient_id)
        
        transaction = wallet_service.transfer(
            source_wallet=sender_wallet,
            destination_wallet=recipient_wallet,
            amount=Decimal(amount),
            description=description or f"Transfer to {recipient_wallet.user}"
        )
        
        return {
            'transaction_id': transaction.id,
            'status': transaction.status,
            'amount': str(transaction.amount)
        }
    except Wallet.DoesNotExist:
        return {'status': 'failed', 'reason': 'Recipient wallet not found'}
    except InsufficientFunds:
        return {'status': 'failed', 'reason': 'Insufficient funds'}
    except WalletLocked:
        return {'status': 'failed', 'reason': 'Wallet is locked'}
```

## Transaction Management

### Getting Transaction History

```python
def get_transaction_history(user, transaction_type=None, status=None, limit=20, offset=0):
    wallet_service = WalletService()
    transaction_service = TransactionService()
    wallet = wallet_service.get_wallet(user)
    
    transactions = transaction_service.list_transactions(
        wallet=wallet,
        transaction_type=transaction_type,
        status=status,
        limit=limit,
        offset=offset
    )
    
    return [{
        'id': tx.id,
        'reference': tx.reference,
        'amount': str(tx.amount),
        'type': tx.transaction_type,
        'status': tx.status,
        'description': tx.description,
        'created_at': tx.created_at.isoformat()
    } for tx in transactions]
```

### Verifying a Transaction

```python
def verify_transaction(reference):
    transaction_service = TransactionService()
    
    try:
        verification_data = transaction_service.verify_paystack_transaction(reference)
        return verification_data
    except Exception as e:
        return {'status': 'failed', 'reason': str(e)}
```

### Refunding a Transaction

```python
def refund_transaction(transaction_id, amount=None, reason=None):
    from wallet.models import Transaction
    
    transaction_service = TransactionService()
    
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        
        refund_transaction = transaction_service.refund_transaction(
            transaction=transaction,
            amount=Decimal(amount) if amount else None,
            reason=reason
        )
        
        return {
            'transaction_id': refund_transaction.id,
            'status': refund_transaction.status,
            'amount': str(refund_transaction.amount)
        }
    except Transaction.DoesNotExist:
        return {'status': 'failed', 'reason': 'Transaction not found'}
```

## Settlements

### Creating a Settlement

```python
def create_settlement(user, bank_account_id, amount, reason=None):
    from wallet.models import BankAccount
    from wallet.exceptions import InsufficientFunds
    
    settlement_service = SettlementService()
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, wallet=wallet)
        
        settlement = settlement_service.create_settlement(
            wallet=wallet,
            bank_account=bank_account,
            amount=Decimal(amount),
            reason=reason or "Manual settlement"
        )
        
        return {
            'settlement_id': settlement.id,
            'reference': settlement.reference,
            'status': settlement.status,
            'amount': str(settlement.amount)
        }
    except BankAccount.DoesNotExist:
        return {'status': 'failed', 'reason': 'Bank account not found'}
    except InsufficientFunds:
        return {'status': 'failed', 'reason': 'Insufficient funds'}
```

### Creating a Settlement Schedule

```python
def create_settlement_schedule(user, bank_account_id, schedule_type, **kwargs):
    from wallet.models import BankAccount
    
    settlement_service = SettlementService()
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, wallet=wallet)
        
        schedule = settlement_service.create_settlement_schedule(
            wallet=wallet,
            bank_account=bank_account,
            schedule_type=schedule_type,
            **kwargs
        )
        
        return {
            'schedule_id': schedule.id,
            'schedule_type': schedule.schedule_type,
            'is_active': schedule.is_active,
            'next_settlement': schedule.next_settlement.isoformat() if schedule.next_settlement else None
        }
    except BankAccount.DoesNotExist:
        return {'status': 'failed', 'reason': 'Bank account not found'}
```

## Using the API in JavaScript

### Depositing Funds

```javascript
// Example using fetch API
async function initiateDeposit(amount, email) {
    try {
        const response = await fetch('/wallet/api/wallets/default/deposit/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken() // Function to get CSRF token
            },
            body: JSON.stringify({
                amount: amount,
                email: email,
                callback_url: window.location.origin + '/payment/callback/'
            })
        });
        
        const data = await response.json();
        
        if (data.authorization_url) {
            // Redirect to Paystack checkout page
            window.location.href = data.authorization_url;
        } else {
            console.error('Error initiating deposit:', data);
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

// Function to verify transaction after redirect back from Paystack
async function verifyTransaction(reference) {
    try {
        const response = await fetch('/wallet/api/transactions/verify/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                reference: reference
            })
        });
        
        return await response.json();
    } catch (error) {
        console.error('Error:', error);
        return { status: 'failed', reason: error.message };
    }
}
```

### Transferring Funds

```javascript
async function transferFunds(destinationWalletId, amount, description) {
    try {
        const response = await fetch('/wallet/api/wallets/default/transfer/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                destination_wallet_id: destinationWalletId,
                amount: amount,
                description: description
            })
        });
        
        return await response.json();
    } catch (error) {
        console.error('Error:', error);
        return { status: 'failed', reason: error.message };
    }
}
```

## Django Views Integration

### Example View for Wallet Dashboard

```python
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from wallet.services.wallet_service import WalletService
from wallet.services.transaction_service import TransactionService

@login_required
def wallet_dashboard(request):
    wallet_service = WalletService()
    transaction_service = TransactionService()
    
    # Get or create user's wallet
    wallet = wallet_service.get_wallet(request.user)
    
    # Get recent transactions
    recent_transactions = transaction_service.list_transactions(
        wallet=wallet,
        limit=10
    )
    
    # Get wallet cards
    cards = wallet.cards.filter(is_active=True)
    
    # Get bank accounts
    bank_accounts = wallet.bank_accounts.filter(is_active=True)
    
    context = {
        'wallet': wallet,
        'balance': wallet.balance,
        'recent_transactions': recent_transactions,
        'cards': cards,
        'bank_accounts': bank_accounts
    }
    
    return render(request, 'wallet/dashboard.html', context)
```

## Handling Webhooks

### Configuring Webhook in Paystack Dashboard

1. Log in to your Paystack Dashboard
2. Go to Settings > API Keys & Webhooks
3. Add the webhook URL: `https://yourdomain.com/wallet/webhook/`
4. Save the webhook settings

### Testing Webhooks Locally

For local development, you can use a tool like [ngrok](https://ngrok.com/) to create a temporary public URL:

```bash
ngrok http 8000
```

Then update your Paystack webhook URL to the ngrok URL (e.g., `https://ab12cd34.ngrok.io/wallet/webhook/`).

## Advanced Use Cases

### Creating a Payment System

```python
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from wallet.services.wallet_service import WalletService
from wallet.exceptions import InsufficientFunds

@login_required
def checkout(request, product_id):
    product = get_object_or_404(Product, id=product_id)  # Assuming you have a Product model
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        wallet_service = WalletService()
        wallet = wallet_service.get_wallet(request.user)
        
        if payment_method == 'wallet':
            # Pay directly from wallet
            try:
                # Deduct amount from wallet
                transaction = wallet_service.withdraw(
                    wallet=wallet,
                    amount=product.price,
                    description=f"Payment for {product.name}"
                )
                
                # Create order or receipt
                order = Order.objects.create(
                    user=request.user,
                    product=product,
                    transaction=transaction,
                    status='paid'
                )
                
                return redirect('order_complete', order_id=order.id)
            except InsufficientFunds:
                return render(request, 'checkout.html', {
                    'product': product,
                    'error': 'Insufficient funds in wallet'
                })
        
        elif payment_method == 'card':
            # Initialize Paystack payment
            charge_data = wallet_service.initialize_card_charge(
                wallet=wallet,
                amount=product.price,
                email=request.user.email,
                callback_url=request.build_absolute_uri(f'/checkout/callback/{product_id}/')
            )
            
            return redirect(charge_data.get('authorization_url'))
    
    return render(request, 'checkout.html', {'product': product})

@login_required
def checkout_callback(request, product_id):
    reference = request.GET.get('reference')
    
    # Verify transaction
    wallet_service = WalletService()
    transaction_data = wallet_service.verify_card_charge(reference)
    
    if transaction_data.get('status') == 'success':
        # Process the payment
        wallet, transaction, card = wallet_service.process_successful_card_charge(transaction_data)
        
        # Get the product
        product = get_object_or_404(Product, id=product_id)
        
        # Create order
        order = Order.objects.create(
            user=request.user,
            product=product,
            transaction=transaction,
            status='paid'
        )
        
        return redirect('order_complete', order_id=order.id)
    else:
        return render(request, 'checkout_failed.html', {
            'reason': transaction_data.get('gateway_response', 'Payment failed')
        })
```

### Implementing a Multi-Tenant Wallet System

```python
# models.py
from django.db import models
from wallet.models import Wallet

class Organization(models.Model):
    name = models.CharField(max_length=100)
    # Other fields...
    
    @property
    def wallet(self):
        # Get the organization's wallet
        from wallet.services.wallet_service import WalletService
        wallet_service = WalletService()
        return wallet_service.get_wallet(self.owner)

class OrganizationMember(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    is_admin = models.BooleanField(default=False)
    # Other fields...

# views.py
@login_required
def organization_payment(request, organization_id):
    organization = get_object_or_404(Organization, id=organization_id)
    
    # Check if user is a member of the organization
    is_member = OrganizationMember.objects.filter(
        organization=organization,
        user=request.user
    ).exists()
    
    if not is_member:
        return HttpResponseForbidden("You are not a member of this organization")
    
    # Get the organization's wallet
    wallet = organization.wallet
    
    # Use the wallet for payments, transactions, etc.
    # ...
```

### Building a Marketplace with Escrow

```python
# models.py
from django.db import models
from wallet.models import Transaction

class Marketplace(models.Model):
    name = models.CharField(max_length=100)
    fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=2.5)
    # Other fields...

class MarketplaceOrder(models.Model):
    buyer = models.ForeignKey('auth.User', related_name='buyer_orders', on_delete=models.CASCADE)
    seller = models.ForeignKey('auth.User', related_name='seller_orders', on_delete=models.CASCADE)
    marketplace = models.ForeignKey(Marketplace, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    buyer_transaction = models.ForeignKey(
        Transaction, related_name='buyer_orders', 
        on_delete=models.SET_NULL, null=True
    )
    seller_transaction = models.ForeignKey(
        Transaction, related_name='seller_orders', 
        on_delete=models.SET_NULL, null=True
    )
    platform_fee = models.DecimalField(max_digits=19, decimal_places=2)
    is_completed = models.BooleanField(default=False)
    # Other fields...

# services.py
from decimal import Decimal
from django.db import transaction
from wallet.services.wallet_service import WalletService

class MarketplaceService:
    def __init__(self):
        self.wallet_service = WalletService()
    
    @transaction.atomic
    def create_order(self, buyer, seller, marketplace, amount):
        # Get wallets
        buyer_wallet = self.wallet_service.get_wallet(buyer)
        
        # Calculate platform fee
        platform_fee = amount * (marketplace.fee_percentage / Decimal('100'))
        seller_amount = amount - platform_fee
        
        # Create order
        order = MarketplaceOrder.objects.create(
            buyer=buyer,
            seller=seller,
            marketplace=marketplace,
            amount=amount,
            platform_fee=platform_fee
        )
        
        # Charge buyer
        buyer_transaction = self.wallet_service.withdraw(
            wallet=buyer_wallet,
            amount=amount,
            description=f"Payment for order #{order.id}"
        )
        
        # Store transaction
        order.buyer_transaction = buyer_transaction
        order.save()
        
        return order
    
    @transaction.atomic
    def complete_order(self, order):
        if order.is_completed:
            raise ValueError("Order is already completed")
        
        # Get seller wallet
        seller_wallet = self.wallet_service.get_wallet(order.seller)
        
        # Calculate seller amount
        seller_amount = order.amount - order.platform_fee
        
        # Pay seller
        seller_transaction = self.wallet_service.deposit(
            wallet=seller_wallet,
            amount=seller_amount,
            description=f"Payment received for order #{order.id}"
        )
        
        # Update order
        order.seller_transaction = seller_transaction
        order.is_completed = True
        order.save()
        
        return order
    
    @transaction.atomic
    def refund_order(self, order):
        if order.is_completed:
            raise ValueError("Cannot refund completed order")
        
        # Get buyer wallet
        buyer_wallet = self.wallet_service.get_wallet(order.buyer)
        
        # Refund buyer
        refund_transaction = self.wallet_service.deposit(
            wallet=buyer_wallet,
            amount=order.amount,
            description=f"Refund for order #{order.id}"
        )
        
        # Delete or mark order as refunded
        order.delete()  # Or update status if you want to keep the record
        
        return refund_transaction
```

## Error Handling

Here's an example of how to handle common wallet exceptions:

```python
from wallet.exceptions import (
    WalletError, InsufficientFunds, WalletLocked, 
    InvalidAmount, TransactionFailed, PaystackAPIError
)

def safe_wallet_operation(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except InsufficientFunds:
        # Handle insufficient funds error
        return {'error': 'Insufficient funds in your wallet'}
    except WalletLocked:
        # Handle locked wallet error
        return {'error': 'Your wallet is currently locked'}
    except InvalidAmount:
        # Handle invalid amount error
        return {'error': 'Invalid amount provided'}
    except TransactionFailed as e:
        # Handle transaction failure
        return {'error': f'Transaction failed: {str(e)}'}
    except PaystackAPIError as e:
        # Handle Paystack API errors
        return {'error': f'Payment gateway error: {str(e)}'}
    except WalletError as e:
        # Handle other wallet-related errors
        return {'error': f'Wallet error: {str(e)}'}
    except Exception as e:
        # Handle unexpected errors
        return {'error': f'An unexpected error occurred: {str(e)}'}
```

## Security Considerations

1. **Authentication & Authorization**: Always check that users can only access their own wallets
2. **Input Validation**: Validate all amounts and parameters to prevent attacks
3. **HTTPS**: Use HTTPS for all API endpoints
4. **CSRF Protection**: Ensure CSRF tokens are used for all POST requests
5. **Webhook Signature Verification**: Always verify webhook signatures
6. **Rate Limiting**: Implement rate limiting to prevent abuse
7. **Logging**: Log all sensitive operations for audit trails

## Sample Projects

For complete examples of using the wallet system, see the following sample projects:

1. [Simple Wallet App](https://github.com/yourusername/sample-wallet-app) - Basic wallet functionality
2. [E-commerce with Wallet Integration](https://github.com/yourusername/ecommerce-wallet) - Integration with an e-commerce site
3. [Marketplace with Escrow](https://github.com/yourusername/marketplace-wallet) - Advanced marketplace with escrow payments

## Next Steps

After learning how to use the wallet system, you might want to explore the [API Reference](api_reference.md) for detailed information on all available APIs. is locked'}
```

## Transaction Management

### Getting Transaction History

```python
def get_transaction_history(user, transaction_type=None, status=None, limit=20, offset=0):
    wallet_service = WalletService()
    transaction_service = TransactionService()
    wallet = wallet_service.get_wallet(user)
    
    transactions = transaction_service.list_transactions(
        wallet=wallet,
        transaction_type=transaction_type,
        status=status,
        limit=limit,
        offset=offset
    )
    
    return [{
        'id': tx.id,
        'reference': tx.reference,
        'amount': str(tx.amount),
        'type': tx.transaction_type,
        'status': tx.status,
        'description': tx.description,
        'created_at': tx.created_at.isoformat()
    } for tx in transactions]
```

### Verifying a Transaction

```python
def verify_transaction(reference):
    transaction_service = TransactionService()
    
    try:
        verification_data = transaction_service.verify_paystack_transaction(reference)
        return verification_data
    except Exception as e:
        return {'status': 'failed', 'reason': str(e)}
```

### Refunding a Transaction

```python
def refund_transaction(transaction_id, amount=None, reason=None):
    from wallet.models import Transaction
    
    transaction_service = TransactionService()
    
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        
        refund_transaction = transaction_service.refund_transaction(
            transaction=transaction,
            amount=Decimal(amount) if amount else None,
            reason=reason
        )
        
        return {
            'transaction_id': refund_transaction.id,
            'status': refund_transaction.status,
            'amount': str(refund_transaction.amount)
        }
    except Transaction.DoesNotExist:
        return {'status': 'failed', 'reason': 'Transaction not found'}
```

## Settlements

### Creating a Settlement

```python
def create_settlement(user, bank_account_id, amount, reason=None):
    from wallet.models import BankAccount
    from wallet.exceptions import InsufficientFunds
    
    settlement_service = SettlementService()
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, wallet=wallet)
        
        settlement = settlement_service.create_settlement(
            wallet=wallet,
            bank_account=bank_account,
            amount=Decimal(amount),
            reason=reason or "Manual settlement"
        )
        
        return {
            'settlement_id': settlement.id,
            'reference': settlement.reference,
            'status': settlement.status,
            'amount': str(settlement.amount)
        }
    except BankAccount.DoesNotExist:
        return {'status': 'failed', 'reason': 'Bank account not found'}
    except InsufficientFunds:
        return {'status': 'failed', 'reason': 'Insufficient funds'}
```

### Creating a Settlement Schedule

```python
def create_settlement_schedule(user, bank_account_id, schedule_type, **kwargs):
    from wallet.models import BankAccount
    
    settlement_service = SettlementService()
    wallet_service = WalletService()
    wallet = wallet_service.get_wallet(user)
    
    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, wallet=wallet)
        
        schedule = settlement_service.create_settlement_schedule(
            wallet=wallet,
            bank_account=bank_account,
            schedule_type=schedule_type,
            **kwargs
        )
        
        return {
            'schedule_id': schedule.id,
            'schedule_type': schedule.schedule_type,
            'is_active': schedule.is_active,
            'next_settlement': schedule.next_settlement.isoformat() if schedule.next_settlement else None
        }
    except BankAccount.DoesNotExist:
        return {'status': 'failed', 'reason': 'Bank account not found'}
```

## Using the API in JavaScript

### Depositing Funds

```javascript
// Example using fetch API
async function initiateDeposit(amount, email) {
    try {
        const response = await fetch('/wallet/api/wallets/default/deposit/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken() // Function to get CSRF token
            },
            body: JSON.stringify({
                amount: amount,
                email: email,
                callback_url: window.location.origin + '/payment/callback/'
            })
        });
        
        const data = await response.json();
        
        if (data.authorization_url) {
            // Redirect to Paystack checkout page
            window.location.href = data.authorization_url;
        } else {
            console.error('Error initiating deposit:', data);
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

// Function to verify transaction after redirect back from Paystack
async function verifyTransaction(reference) {
    try {
        const response = await fetch('/wallet/api/transactions/verify/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                reference: reference
            })
        });
        
        return await response.json();
    } catch (error) {
        console.error('Error:', error);
        return { status: 'failed', reason: error.message };
    }
}
```

### Transferring Funds

```javascript
async function transferFunds(destinationWalletId, amount, description) {
    try {
        const response = await fetch('/wallet/api/wallets/default/transfer/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                destination_wallet_id: destinationWalletId,
                amount: amount,
                description: description
            })
        });
        
        return await response.json();
    } catch (error) {
        console.error('Error:', error);
        return { status: 'failed', reason: error.message };
    }
}
```

## Django Views Integration

### Example View for Wallet Dashboard

```python
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from wallet.services.wallet_service import WalletService
from wallet.services.transaction_service import TransactionService

@login_required
def wallet_dashboard(request):
    wallet_service = WalletService()
    transaction_service = TransactionService()
    
    # Get or create user's wallet
    wallet = wallet_service.get_wallet(request.user)
    
    # Get recent transactions
    recent_transactions = transaction_service.list_transactions(
        wallet=wallet,
        limit=10
    )
    
    # Get wallet cards
    cards = wallet.cards.filter(is_active=True)
    
    # Get bank accounts
    bank_accounts = wallet.bank_accounts.filter(is_active=True)
    
    context = {
        'wallet': wallet,
        'balance': wallet.balance,
        'recent_transactions': recent_transactions,
        'cards': cards,
        'bank_accounts': bank_accounts
    }
    
    return render(request, 'wallet/dashboard.html', context)
```

## Handling Webhooks

### Configuring Webhook in Paystack Dashboard

1. Log in to your Paystack Dashboard
2. Go to Settings > API Keys & Webhooks
3. Add the webhook URL: `https://yourdomain.com/wallet/webhook/`
4. Save the webhook settings

### Testing Webhooks Locally

For local development, you can use a tool like [ngrok](https://ngrok.com/) to create a temporary public URL:

```bash
ngrok http 8000
```

Then update your Paystack webhook URL to the ngrok URL (e.g., `https://ab12cd34.ngrok.io/wallet/webhook/`).

## Advanced Use Cases

### Creating a Payment System

```python
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from wallet.services.wallet_service import WalletService
from wallet.exceptions import InsufficientFunds

@login_required
def checkout(request, product_id):
    product = get_object_or_404(Product, id=product_id)  # Assuming you have a Product model
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        wallet_service = WalletService()
        wallet = wallet_service.get_wallet(request.user)
        
        if payment_method == 'wallet':
            # Pay directly from wallet
            try:
                # Deduct amount from wallet
                transaction = wallet_service.withdraw(
                    wallet=wallet,
                    amount=product.price,
                    description=f"Payment for {product.name}"
                )
                
                # Create order or receipt
                order = Order.objects.create(
                    user=request.user,
                    product=product,
                    transaction=transaction,
                    status='paid'
                )
                
                return redirect('order_complete', order_id=order.id)
            except InsufficientFunds:
                return render(request, 'checkout.html', {
                    'product': product,
                    'error': 'Insufficient funds in wallet'
                })
        
        elif payment_method == 'card':
            # Initialize Paystack payment
            charge_data = wallet_service.initialize_card_charge(
                wallet=wallet,
                amount=product.price,
                email=request.user.email,
                callback_url=request.build_absolute_uri(f'/checkout/callback/{product_id}/')
            )
            
            return redirect(charge_data.get('authorization_url'))
    
    return render(request, 'checkout.html', {'product': product})

@login_required
def checkout_callback(request, product_id):
    reference = request.GET.get('reference')
    
    # Verify transaction
    wallet_service = WalletService()
    transaction_data = wallet_service.verify_card_charge(reference)
    
    if transaction_data.get('status') == 'success':
        # Process the payment
        wallet, transaction, card = wallet_service.process_successful_card_charge(transaction_data)