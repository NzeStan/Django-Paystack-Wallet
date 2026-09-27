"""
Transaction endpoints.

    GET  transactions/                     ?type=&status=&direction=&search=&start_date=&end_date=
    GET  transactions/{id}/
    POST transactions/verify/              {reference} - re-check a deposit with Paystack
    POST transactions/{id}/cancel/         unpaid deposit (owner) or escrowed payment (staff)
    POST transactions/{id}/release/        release an escrowed payment to the seller (buyer or staff)
    POST transactions/{id}/refund/         refund a deposit to the payer's card/bank (staff)
    POST transactions/{id}/reverse/        reverse a transfer or payment (staff)
    GET  transactions/statistics/
    GET  transactions/summary/
    GET  transactions/export/?export_format=csv|xlsx|pdf
"""
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from wallet.apis.base import WalletAPIMixin, error_response
from wallet.apis.wallet_api import _parse_when
from wallet.constants import TRANSACTION_TYPE_DEPOSIT, TRANSACTION_TYPE_PAYMENT
from wallet.exceptions import InvalidTransactionState
from wallet.models import Transaction
from wallet.serializers.transaction_serializer import (
    ReasonSerializer,
    RefundSerializer,
    TransactionDetailSerializer,
    TransactionSerializer,
    VerifyTransactionSerializer,
)
from wallet.services.deposit_service import DepositService
from wallet.services.transaction_service import TransactionService
from wallet.services.transfer_service import TransferService
from wallet.utils.exporters import EXPORT_FORMATS, export_queryset

EXPORT_FIELDS = [
    'reference', 'transaction_type', 'direction', 'status', 'amount', 'fees', 'total_amount', 'balance_after',
    'payment_method', 'description', 'created_at', 'completed_at',
]


class TransactionViewSet(WalletAPIMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer
    staff_actions = ('refund', 'reverse')
    # Actions where staff may act on any user's transaction
    staff_wide_actions = ('refund', 'reverse', 'release', 'cancel')
    idempotent_actions = ('refund', 'reverse', 'release', 'cancel')

    def get_queryset(self):
        queryset = Transaction.objects.with_full_details()
        if not (self.request.user.is_staff and self.action in self.staff_wide_actions):
            queryset = queryset.filter(wallet__user=self.request.user)
        params = self.request.query_params
        filters = {
            'transaction_type': params.get('type') or params.get('transaction_type'),
            'status': params.get('status'),
            'direction': params.get('direction'),
            'payment_method': params.get('payment_method'),
        }
        queryset = queryset.filter(**{k: v for k, v in filters.items() if v})
        queryset = queryset.in_date_range(_parse_when(params.get('start_date')),
                                          _parse_when(params.get('end_date'), end=True))
        if params.get('search'):
            queryset = queryset.filter(Q(reference__icontains=params['search'])
                                       | Q(description__icontains=params['search']))
        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        return TransactionDetailSerializer if self.action == 'retrieve' else TransactionSerializer

    @action(detail=False, methods=['post'])
    def verify(self, request):
        data = self.validated(VerifyTransactionSerializer)
        txn = self.get_queryset().filter(reference=data['reference']).first()
        if txn is None:
            return error_response(_("Transaction not found"), status.HTTP_404_NOT_FOUND, 'not_found')
        if txn.transaction_type != TRANSACTION_TYPE_DEPOSIT:
            raise InvalidTransactionState(_("Only deposits can be verified"))
        DepositService().verify_deposit(txn.reference)
        txn.refresh_from_db()
        return Response(TransactionDetailSerializer(txn).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        txn = self.get_object()
        if txn.transaction_type == TRANSACTION_TYPE_PAYMENT and not request.user.is_staff:
            # A buyer could otherwise take the goods and then cancel the escrow.
            raise PermissionDenied(_("Escrowed payments can only be cancelled by staff"))
        data = self.validated(ReasonSerializer)
        txn = TransactionService().cancel_transaction(txn, data.get('reason'), performed_by=request.user)
        return Response(TransactionDetailSerializer(txn).data)

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        txn = self.get_object()
        txn = TransferService().release_payment(txn, performed_by=request.user)
        return Response(TransactionDetailSerializer(txn).data)

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        txn = self.get_object()
        data = self.validated(RefundSerializer)
        refund = TransactionService().refund_deposit(txn, amount=data.get('amount'), reason=data.get('reason'),
                                                     performed_by=request.user)
        return Response(TransactionDetailSerializer(refund).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        txn = self.get_object()
        data = self.validated(ReasonSerializer)
        reversal = TransactionService().reverse_transaction(txn, reason=data.get('reason'),
                                                           performed_by=request.user)
        return Response(TransactionDetailSerializer(reversal).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        stats = TransactionService().get_transaction_statistics(
            wallet=self.get_user_wallet(), start_date=_parse_when(request.query_params.get('start_date')),
            end_date=_parse_when(request.query_params.get('end_date'), end=True),
        )
        return Response({key: str(value) if not isinstance(value, (dict, int)) else value
                         for key, value in stats.items()})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        summary = TransactionService().get_transaction_summary(wallet=self.get_user_wallet())
        return Response(_stringify(summary))

    @action(detail=False, methods=['get'])
    def export(self, request):
        export_format = request.query_params.get('export_format', 'csv')
        if export_format not in EXPORT_FORMATS:
            return error_response(_("Use export_format=csv, xlsx or pdf"), status.HTTP_400_BAD_REQUEST, 'invalid_format')
        try:
            return export_queryset(self.get_queryset(), EXPORT_FIELDS, export_format, 'transactions',
                                   title='Transactions')
        except ImproperlyConfigured as exc:     # optional export libraries not installed
            return error_response(str(exc), status.HTTP_501_NOT_IMPLEMENTED, 'export_unavailable')


def _stringify(value):
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    if isinstance(value, (int, str)) or value is None:
        return value
    return str(value)
