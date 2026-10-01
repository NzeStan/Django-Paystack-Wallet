"""
Include in your project::

    path('wallet/', include('wallet.urls')),

which gives ``/wallet/api/...``, ``/wallet/webhook/`` and ``/wallet/callback/``.

Only need some parts? Build your own urlpatterns from ``wallet.urls.router``
or register the individual viewsets from :mod:`wallet.apis`.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from wallet.apis.bank_account_api import BankAccountViewSet, BankViewSet
from wallet.apis.card_api import CardViewSet
from wallet.apis.settlement_api import SettlementScheduleViewSet, SettlementViewSet
from wallet.apis.transaction_api import TransactionViewSet
from wallet.apis.wallet_api import WalletViewSet
from wallet.apis.webhook_api import (
    WebhookDeliveryAttemptViewSet,
    WebhookEndpointViewSet,
    WebhookEventViewSet,
    paystack_webhook,
)
from wallet.views import PaymentCallbackView

app_name = 'wallet'

router = DefaultRouter()
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'cards', CardViewSet, basename='card')
router.register(r'banks', BankViewSet, basename='bank')
router.register(r'bank-accounts', BankAccountViewSet, basename='bank-account')
router.register(r'settlements', SettlementViewSet, basename='settlement')
router.register(r'settlement-schedules', SettlementScheduleViewSet, basename='settlement-schedule')
router.register(r'webhook-events', WebhookEventViewSet, basename='webhook-event')
router.register(r'webhook-endpoints', WebhookEndpointViewSet, basename='webhook-endpoint')
router.register(r'webhook-deliveries', WebhookDeliveryAttemptViewSet, basename='webhook-delivery')

urlpatterns = [
    path('api/', include(router.urls)),
    path('webhook/', paystack_webhook, name='paystack-webhook'),
    path('callback/', PaymentCallbackView.as_view(), name='payment-callback'),
]
