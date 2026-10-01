"""
Banks and payout bank accounts.

    GET    banks/                          ?country=&currency=&search=
    GET    bank-accounts/
    POST   bank-accounts/                  {bank_code, account_number} - verified with Paystack
    POST   bank-accounts/resolve/          {bank_code, account_number} -> account name
    GET    bank-accounts/{id}/
    DELETE bank-accounts/{id}/
    POST   bank-accounts/{id}/set-default/
"""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from wallet.apis.base import WalletAPIMixin
from wallet.models import Bank, BankAccount
from wallet.serializers.bank_account_serializer import (
    BankAccountCreateSerializer,
    BankAccountSerializer,
    BankSerializer,
    ResolveAccountSerializer,
)
from wallet.services.bank_account_service import BankAccountService


class BankViewSet(WalletAPIMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = BankSerializer

    def get_queryset(self):
        queryset = Bank.objects.active()
        params = self.request.query_params
        if params.get('country'):
            queryset = queryset.filter(country__iexact=params['country'])
        if params.get('currency'):
            queryset = queryset.filter(currency__iexact=params['currency'])
        if params.get('search'):
            queryset = queryset.search(params['search'])
        return queryset.order_by('name')


class BankAccountViewSet(WalletAPIMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                         viewsets.GenericViewSet):
    serializer_class = BankAccountSerializer
    feature = 'WITHDRAWALS'
    throttle_scopes = {'create': 'resolve', 'resolve': 'resolve'}

    def get_queryset(self):
        return BankAccount.objects.filter(
            wallet__user=self.request.user, is_active=True,
        ).select_related('bank').order_by('-is_default', '-created_at')

    def create(self, request, *args, **kwargs):
        wallet = self.get_user_wallet()
        data = self.validated(BankAccountCreateSerializer)
        account = BankAccountService().add_bank_account(
            wallet, bank_code=data['bank_code'], account_number=data['account_number'],
            account_type=data.get('account_type'), currency=data.get('currency'),
            set_default=data.get('set_default'),
        )
        return Response(BankAccountSerializer(account).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        BankAccountService().remove_bank_account(instance)

    @action(detail=False, methods=['post'])
    def resolve(self, request):
        data = self.validated(ResolveAccountSerializer)
        result = BankAccountService().resolve_account(data['account_number'], data['bank_code'])
        return Response({'account_number': result.get('account_number'), 'account_name': result.get('account_name'),
                         'bank_code': data['bank_code']})

    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        account = self.get_object()
        account.set_as_default()
        return Response(BankAccountSerializer(account).data)
