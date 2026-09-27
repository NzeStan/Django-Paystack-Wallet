# Extending

The package is built so you can take only what you need and plug your own behaviour in
without forking it.

## Signals

Every money movement sends a signal **after the database transaction commits**, so you
never act on something that rolls back.

```python
# myapp/receivers.py
from django.dispatch import receiver
from wallet.signals import deposit_completed, transfer_completed, withdrawal_failed

@receiver(deposit_completed)
def on_deposit(sender, transaction, wallet, **kwargs):
    Order.objects.filter(reference=transaction.metadata.get('order_ref')).update(paid=True)

@receiver(transfer_completed)
def on_transfer(sender, transaction, wallet, recipient_transaction, recipient_wallet, **kwargs):
    push.send(recipient_wallet.user, f"You received {recipient_transaction.total_amount}")

@receiver(withdrawal_failed)
def on_withdrawal_failed(sender, transaction, wallet, reason, reversed, **kwargs):
    ...
```

Connect them in your `AppConfig.ready()`, as usual.

| Signal | Arguments |
| --- | --- |
| `wallet_created` | `wallet` |
| `wallet_locked` / `wallet_unlocked` | `wallet`, (`reason`) |
| `deposit_initialized` | `transaction`, `wallet`, `authorization_url`, `access_code` |
| `deposit_completed` | `transaction`, `wallet` |
| `deposit_failed` | `transaction`, `wallet`, `reason` |
| `withdrawal_initiated` | `transaction`, `wallet`, `requires_otp` |
| `withdrawal_completed` | `transaction`, `wallet` |
| `withdrawal_failed` | `transaction`, `wallet`, `reason`, `reversed` |
| `transfer_completed` | `transaction`, `wallet`, `recipient_transaction`, `recipient_wallet` |
| `payment_completed` | `transaction`, `wallet`, `merchant_wallet`, `escrow` |
| `payment_released` | `transaction`, `wallet`, `merchant_wallet`, `merchant_transaction` |
| `payment_cancelled` | `transaction`, `wallet` |
| `refund_initiated` / `refund_completed` | `transaction`, `wallet`, `original_transaction` |
| `refund_failed` | `transaction`, `wallet`, `original_transaction`, `reason` |
| `transaction_reversed` | `transaction`, `wallet`, `original_transaction` |
| `transaction_status_changed` | `transaction`, `wallet`, `old_status`, `new_status` (every change) |
| `card_saved` | `card`, `wallet`, `created` |
| `bank_account_added` | `bank_account`, `wallet` |
| `dedicated_account_assigned` / `dedicated_account_failed` | `wallet`, `data` |
| `customer_identification` | `wallet`, `success`, `data` |
| `settlement_completed` / `settlement_failed` | `settlement`, `wallet`, (`reason`) |
| `paystack_webhook_received` | `event`, `data`, `webhook_event`, `handled`: **every** Paystack event |
| `dispute_event` | `event`, `data`, `transaction` |

### Handling Paystack events the wallet doesn't use

Subscriptions, invoices, payment requests and so on arrive through
`paystack_webhook_received`, already signature-checked and de-duplicated:

```python
from wallet.signals import paystack_webhook_received

@receiver(paystack_webhook_received)
def on_paystack_event(sender, event, data, webhook_event, handled, **kwargs):
    if event == 'subscription.create':
        Subscription.objects.update_or_create(code=data['subscription_code'], defaults={...})
    elif event == 'invoice.payment_failed':
        ...
```

## Notifications

The wallet sends nothing by itself. List backends to turn notifications on:

```python
WALLET_NOTIFICATION_BACKENDS = [
    'wallet.notifications.backends.EmailNotificationBackend',   # Django email
    'myproject.notifications.SMSBackend',
]
```

Write a backend for any channel:

```python
from wallet.notifications.backends import BaseNotificationBackend

class SMSBackend(BaseNotificationBackend):
    events = {'deposit_completed', 'transfer_received', 'withdrawal_failed'}   # None = all events

    def send(self, event, user, context):
        # context: transaction, wallet, amount, total_amount, fees, reference, balance, description, ...
        sms_client.send(user.profile.phone, self.render_text(event, context))
```

Events: `deposit_completed`, `deposit_failed`, `withdrawal_completed`,
`withdrawal_failed`, `transfer_sent`, `transfer_received`, `payment_made`,
`payment_received`, `payment_cancelled`, `refund_completed`, `refund_failed`,
`dedicated_account_assigned`, `settlement_completed`, `settlement_failed`,
`wallet_locked`.

Change the wording by overriding the templates `wallet/notifications/<event>.txt`
(falling back to `wallet/notifications/default.txt`) in your project's template
directory. A failing backend is logged and never breaks a payment. For async delivery,
send from a Celery task inside your backend (or use an async email backend).

## Custom fee pricing

Subclass the calculator and override `get_fee` (and optionally `get_default_bearer` or
`is_enabled`):

```python
# myproject/fees.py
from decimal import Decimal
from wallet.services.fee_service import FeeCalculator

class MyFees(FeeCalculator):
    def get_fee(self, amount, transaction_type, payment_channel=None):
        if transaction_type == 'transfer' and self.wallet and self.wallet.metadata.get('vip'):
            return Decimal('0'), 'custom', None, {'rule': 'vip free transfers'}
        if transaction_type == 'payment':
            return (amount * Decimal('0.03')).quantize(Decimal('0.01')), 'custom', None, {'rule': '3% commission'}
        return super().get_fee(amount, transaction_type, payment_channel)
```

```python
WALLET_ENABLE_FEES = True
WALLET_ENABLE_INTERNAL_TRANSFER_FEES = True   # per-type switches still apply...
WALLET_ENABLE_PAYMENT_FEES = True             # ...unless you also override is_enabled()
WALLET_FEE_CALCULATOR = 'myproject.fees.MyFees'
```

`self.wallet` is the paying wallet (or `None`), so pricing can depend on anything about the
user. Bearer logic, rounding, the customer gross-up, recording to `FeeHistory` and the
ledger movements all keep working.

For admin-editable pricing without code, use `WALLET_USE_DATABASE_FEE_CONFIG = True` and
manage **Fee configurations** in the Django admin.

## Your own endpoints

Use the service layer from your own views:

```python
from rest_framework.decorators import api_view
from rest_framework.response import Response
from wallet.exceptions import WalletError
from wallet.services import WalletService

@api_view(['POST'])
def checkout(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    service = WalletService()
    try:
        txn = service.pay(service.get_wallet(request.user), order.total,
                          merchant_wallet=order.seller.wallet, escrow=True,
                          metadata={'order_id': order.pk}, reference=f'ORDER-{order.pk:08d}')
    except WalletError as exc:
        return Response(exc.as_dict(), status=exc.http_status)
    order.mark_paid(txn)
    return Response({'transaction': str(txn.pk)})
```

Or expose only some of the built-in API:

```python
from rest_framework.routers import DefaultRouter
from wallet.apis import WalletViewSet, TransactionViewSet, paystack_webhook

router = DefaultRouter()
router.register('wallets', WalletViewSet, basename='wallet')
router.register('transactions', TransactionViewSet, basename='transaction')

urlpatterns = [
    path('api/', include(router.urls)),
    path('paystack/webhook/', paystack_webhook),
]
```

Subclass a viewset to change behaviour. All viewsets use `WalletAPIMixin`, which maps
wallet exceptions to HTTP responses and checks feature switches.

## Permissions

`WALLET_API_PERMISSION_CLASSES` applies to every wallet endpoint:

```python
WALLET_API_PERMISSION_CLASSES = [
    'rest_framework.permissions.IsAuthenticated',
    'myproject.permissions.HasVerifiedKYC',
]
```

`wallet.permissions` has reusable pieces: `IsWalletOwner`, `HasOperationalWallet`.

## Phone numbers

The built-in normaliser handles local and international formats for one default country
code. For stricter validation across many countries, plug in your own:

```python
# myproject/phones.py
import phonenumbers

def normalize(value):
    number = phonenumbers.parse(value, 'NG')
    if not phonenumbers.is_valid_number(number):
        raise ValueError('invalid')
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
```

```python
WALLET_PHONE_NUMBER_NORMALIZER = 'myproject.phones.normalize'
```

## Using the Paystack client directly

```python
from wallet.paystack import PaystackClient, get_paystack_client

paystack = get_paystack_client()              # uses PAYSTACK_SECRET_KEY
other = PaystackClient(secret_key='sk_live_other_business')   # e.g. multi-tenant

paystack.transactions.totals()
paystack.request('GET', 'transaction', params={'status': 'success'}, raw=True)   # includes `meta`
```

Errors raise `wallet.exceptions.PaystackAPIError`. Its `is_definitive` is `True` when
Paystack rejected the request (4xx) and `False` when the outcome is unknown (network
error, 5xx). Never assume a timed-out charge or transfer failed.

Verify signatures of Paystack webhooks you receive elsewhere:

```python
from wallet.paystack import verify_signature
verify_signature(request.body, request.headers['X-Paystack-Signature'])
```

## Background processing

With `WALLET_USE_CELERY = True`, webhook processing, customer/DVA provisioning, webhook
forwarding and threshold payouts run as Celery tasks (`wallet.tasks`). Without Celery the
same code runs inline, and the tasks remain importable as plain functions.

## Testing your integration

Mock Paystack at the HTTP level (for example with `responses`) and call the services, or
post signed webhooks to your endpoint:

```python
import json
from wallet.paystack import compute_signature

body = json.dumps({'event': 'charge.success', 'data': {...}}).encode()
client.post('/wallet/webhook/', data=body, content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=compute_signature(body))
```

Remember that signals are sent on commit: in Django `TestCase`s wrap the code in
`self.captureOnCommitCallbacks(execute=True)` (pytest-django:
`django_capture_on_commit_callbacks`).
