"""
Settlements (payouts) and settlement schedules.

    GET  settlements/
    POST settlements/                       {amount, bank_account_id?, reason?}
    GET  settlements/{id}/
    POST settlements/{id}/finalize/         {otp}
    POST settlements/{id}/verify/
    POST settlements/{id}/retry/
    GET  settlements/statistics/
    CRUD settlement-schedules/  (+ POST {id}/activate/, {id}/deactivate/)
"""
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from wallet.apis.base import WalletAPIMixin, error_response
from wallet.models import BankAccount, Settlement, SettlementSchedule
from wallet.serializers.settlement_serializer import (
    OtpSerializer,
    SettlementCreateSerializer,
    SettlementScheduleSerializer,
    SettlementSerializer,
)
from wallet.services.settlement_service import SettlementService


class SettlementViewSet(WalletAPIMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SettlementSerializer
    feature = 'SETTLEMENTS'
    throttle_scopes = {'create': 'money', 'finalize': 'otp'}
    idempotent_actions = ('create', 'finalize')

    def get_queryset(self):
        queryset = Settlement.objects.with_full_details().filter(wallet__user=self.request.user)
        if self.request.query_params.get('status'):
            queryset = queryset.filter(status=self.request.query_params['status'])
        return queryset.order_by('-created_at')

    def create(self, request, *args, **kwargs):
        wallet = self.get_user_wallet()
        data = self.validated(SettlementCreateSerializer)
        self.check_pin(wallet, data.get('pin'))
        accounts = BankAccount.objects.filter(wallet=wallet, is_active=True)
        account = accounts.filter(pk=data['bank_account_id']).first() if data.get('bank_account_id') else \
            accounts.order_by('-is_default', '-created_at').first()
        if account is None:
            return error_response(_("Bank account not found"), status.HTTP_404_NOT_FOUND, 'bank_account_not_found')
        settlement = SettlementService().create_settlement(wallet, account, data['amount'], reason=data.get('reason'))
        return Response(SettlementSerializer(settlement).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        data = self.validated(OtpSerializer)
        settlement = SettlementService().finalize_settlement(self.get_object(), data['otp'])
        return Response(SettlementSerializer(settlement).data)

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        settlement = SettlementService().verify_settlement(self.get_object())
        return Response(SettlementSerializer(settlement).data)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        settlement = SettlementService().retry_settlement(self.get_object())
        return Response(SettlementSerializer(settlement).data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        stats = SettlementService().get_settlement_stats(wallet=self.get_user_wallet())
        return Response({key: value if isinstance(value, (int, float)) else str(value) for key, value in stats.items()})


class SettlementScheduleViewSet(WalletAPIMixin, viewsets.ModelViewSet):
    serializer_class = SettlementScheduleSerializer
    feature = 'SETTLEMENTS'

    def get_queryset(self):
        return SettlementSchedule.objects.with_full_details().filter(wallet__user=self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self.request, 'user', None) and self.request.user.is_authenticated:
            context['wallet'] = self.get_user_wallet()
        return context

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        return Response(SettlementScheduleSerializer(self.get_object().activate(),
                                                     context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        return Response(SettlementScheduleSerializer(self.get_object().deactivate(),
                                                     context=self.get_serializer_context()).data)
