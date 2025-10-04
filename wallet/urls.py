from django.urls import path, include
from rest_framework.routers import DefaultRouter

from wallet.apis.wallet_api import WalletViewSet
from wallet.apis.transaction_api import TransactionViewSet
from wallet.apis.card_api import CardViewSet
from wallet.apis.bank_account_api import BankAccountViewSet, BankViewSet
from wallet.apis.settlement_api import SettlementViewSet, SettlementScheduleViewSet
from wallet.apis.webhook_api import paystack_webhook
from .views import SuccessPageView
# Create a router and register viewsets
router = DefaultRouter()
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'cards', CardViewSet, basename='card')
router.register(r'bank-accounts', BankAccountViewSet, basename='bank-account')
router.register(r'banks', BankViewSet, basename='bank')
router.register(r'settlements', SettlementViewSet, basename='settlement')
router.register(r'settlement-schedules', SettlementScheduleViewSet, basename='settlement-schedule')

# URLs for the API
urlpatterns = [
    # API routes
    path('api/', include(router.urls)),
    
    # Webhook URL
    path('webhook/', paystack_webhook, name='paystack-webhook'),

    #succes template
    path("success/", SuccessPageView.as_view(), name="success"),
]