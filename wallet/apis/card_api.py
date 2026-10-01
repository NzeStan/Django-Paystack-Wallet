"""
Saved cards. Cards are added automatically when the user pays with a card.

    GET    cards/
    GET    cards/{id}/
    DELETE cards/{id}/                 remove (and revoke on Paystack)
    POST   cards/{id}/set-default/
    POST   cards/{id}/charge/          {amount} top up the wallet from this card
"""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from wallet.apis.base import WalletAPIMixin, request_context
from wallet.models import Card
from wallet.serializers.card_serializer import CardSerializer
from wallet.serializers.transaction_serializer import TransactionDetailSerializer
from wallet.serializers.wallet_serializer import ChargeCardSerializer
from wallet.services.wallet_service import WalletService


class CardViewSet(WalletAPIMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                  viewsets.GenericViewSet):
    serializer_class = CardSerializer
    feature = 'CARDS'
    throttle_scopes = {'charge': 'money'}
    idempotent_actions = ('charge',)

    def get_queryset(self):
        queryset = Card.objects.filter(wallet__user=self.request.user)
        if self.action == 'list' and self.request.query_params.get('include_inactive') not in ('1', 'true'):
            queryset = queryset.filter(is_active=True)
        return queryset.order_by('-is_default', '-created_at')

    def perform_destroy(self, instance):
        WalletService().remove_card(instance)

    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        card = self.get_object()
        if not card.is_active:
            return Response({'detail': 'Card is not active'}, status=status.HTTP_400_BAD_REQUEST)
        card.set_as_default()
        return Response(CardSerializer(card).data)

    @action(detail=True, methods=['post'])
    def charge(self, request, pk=None):
        card = self.get_object()
        data = self.validated(ChargeCardSerializer)
        self.check_pin(card.wallet, data.get('pin'))
        txn = WalletService().charge_card(
            card, data['amount'], reference=data.get('reference'), metadata=data.get('metadata'),
            fee_bearer=data.get('fee_bearer'), description=data.get('description'), **request_context(request),
        )
        txn.refresh_from_db()
        code = status.HTTP_200_OK if txn.is_successful else status.HTTP_202_ACCEPTED
        return Response(TransactionDetailSerializer(txn).data, status=code)
