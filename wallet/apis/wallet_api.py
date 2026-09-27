"""
Wallet endpoints (the wallet of the logged-in user).

``{id}`` may be the wallet UUID or ``me`` (``default`` also works).

    GET    wallets/                           list (the user's wallet)
    GET    wallets/me/                        details
    PATCH  wallets/me/                        update tag / phone_number
    GET    wallets/me/balance/
    GET    wallets/me/transactions/           ?type=&status=&direction=&search=
    GET    wallets/me/statement/              ?start_date=&end_date=
    POST   wallets/me/deposit/                Paystack checkout (card, bank, USSD, transfer, ...)
    POST   wallets/me/verify-deposit/         {reference}
    POST   wallets/me/charge-card/            saved card top-up
    POST   wallets/me/withdraw/               to bank account
    POST   wallets/me/finalize-withdrawal/    {otp, transaction_id|reference|transfer_code}
    POST   wallets/me/resend-otp/
    POST   wallets/me/transfer/               {recipient: id|tag|phone|email, amount}
    POST   wallets/me/pay/                    wallet checkout (optionally escrow to a seller)
    GET    wallets/lookup/?recipient=         confirm a recipient before sending
    POST   wallets/me/set-pin/
    GET    wallets/me/dedicated-account/
    POST   wallets/me/dedicated-account/      create a DVA
    POST   wallets/me/requery-dedicated-account/
    POST   wallets/me/validate-customer/      Paystack identity validation (needed for DVA)
    POST   wallets/fee-quote/
"""
import uuid
from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext_lazy as _
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from wallet.apis.base import WalletAPIMixin, error_response, request_context
from wallet.conf import is_feature_enabled
from wallet.constants import TRANSACTION_TYPE_WITHDRAWAL
from wallet.exceptions import FeatureDisabled, PinRequired, WalletNotFound
from wallet.models import BankAccount, Card, Transaction, Wallet
from wallet.serializers.fee_serializer import FeeQuoteSerializer
from wallet.serializers.transaction_serializer import TransactionDetailSerializer, TransactionSerializer
from wallet.serializers.wallet_serializer import (
    ChargeCardSerializer,
    CustomerValidationSerializer,
    DedicatedAccountSerializer,
    DepositSerializer,
    FinalizeWithdrawalSerializer,
    PaySerializer,
    RecipientLookupSerializer,
    ResendOtpSerializer,
    SetPinSerializer,
    TransferSerializer,
    VerifyDepositSerializer,
    WalletDetailSerializer,
    WalletSerializer,
    WalletUpdateSerializer,
    WithdrawSerializer,
)
from wallet.services.fee_service import get_fee_calculator
from wallet.services.wallet_service import WalletService

ME = ('me', 'default')


def _parse_when(value, end=False):
    """Parse ``2026-09-30`` or an ISO datetime into an aware datetime (dates cover the whole day)."""
    if not value:
        return None
    try:
        day = parse_date(value)
    except ValueError:
        day = None
    if day is not None:
        return timezone.make_aware(datetime.combine(day, time.max if end else time.min))
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


class WalletViewSet(WalletAPIMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = WalletSerializer
    throttle_scopes = {
        'lookup': 'lookup', 'set_pin': 'pin',
        'deposit': 'money', 'charge_card': 'money', 'withdraw': 'money', 'transfer': 'money', 'pay': 'money',
        'finalize_withdrawal': 'otp', 'resend_otp': 'otp', 'validate_customer': 'resolve',
    }
    idempotent_actions = ('deposit', 'charge_card', 'withdraw', 'transfer', 'pay', 'finalize_withdrawal')

    def get_queryset(self):
        return Wallet.objects.filter(user=self.request.user).select_related('user')

    def get_object(self):
        pk = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        if pk in ME:
            wallet = self.get_user_wallet()
        else:
            wallet = self.get_queryset().filter(pk=pk).first() if _is_uuid(pk) else None
            if wallet is None:
                raise WalletNotFound()
        self.check_object_permissions(self.request, wallet)
        return wallet

    def get_serializer_class(self):
        return WalletDetailSerializer if self.action == 'retrieve' else WalletSerializer

    @property
    def service(self):
        return WalletService()

    def list(self, request, *args, **kwargs):
        self.get_user_wallet()
        return super().list(request, *args, **kwargs)

    def partial_update(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(WalletUpdateSerializer)
        service = self.service
        if 'tag' in data:
            service.set_tag(wallet, data['tag'])
        if 'phone_number' in data:
            service.set_phone_number(wallet, data['phone_number'] or None)
        return Response(WalletDetailSerializer(wallet).data)

    # ------------------------------------------------------------------
    # Balance & history
    # ------------------------------------------------------------------

    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        wallet = self.get_object()
        wallet.refresh_balance()
        return Response({
            'balance': str(wallet.balance.amount),
            'currency': wallet.currency,
            'is_operational': wallet.is_operational,
            'updated_at': wallet.updated_at,
        })

    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        wallet = self.get_object()
        params = request.query_params
        queryset = self.service.get_transaction_history(
            wallet, transaction_type=params.get('type'), status=params.get('status'),
            direction=params.get('direction'), start_date=_parse_when(params.get('start_date')),
            end_date=_parse_when(params.get('end_date'), end=True),
        )
        if params.get('search'):
            queryset = queryset.filter(Q(reference__icontains=params['search'])
                                       | Q(description__icontains=params['search']))
        return self.paginated(queryset, TransactionSerializer)

    @action(detail=True, methods=['get'])
    def statement(self, request, pk=None):
        wallet = self.get_object()
        queryset = self.service.get_statement(
            wallet, _parse_when(request.query_params.get('start_date')),
            _parse_when(request.query_params.get('end_date'), end=True),
        )
        return self.paginated(queryset, TransactionSerializer)

    # ------------------------------------------------------------------
    # Deposits
    # ------------------------------------------------------------------

    @action(detail=True, methods=['post'])
    def deposit(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(DepositSerializer)
        result = self.service.initialize_deposit(
            wallet, data['amount'], email=data.get('email'), callback_url=data.get('callback_url'),
            reference=data.get('reference'), metadata=data.get('metadata'), channels=data.get('channels'),
            fee_bearer=data.get('fee_bearer'), description=data.get('description'), **request_context(request),
        )
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='verify-deposit')
    def verify_deposit(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(VerifyDepositSerializer)
        txn = Transaction.objects.filter(reference=data['reference'], wallet=wallet).first()
        if txn is None:
            return error_response(_("Deposit not found"), status.HTTP_404_NOT_FOUND, 'not_found')
        txn = self.service.verify_deposit(txn.reference) or txn
        txn.refresh_from_db()
        return Response(TransactionDetailSerializer(txn).data)

    @action(detail=True, methods=['post'], url_path='charge-card')
    def charge_card(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(ChargeCardSerializer)
        self.check_pin(wallet, data.get('pin'))
        cards = Card.objects.filter(wallet=wallet, is_active=True)
        card = cards.filter(pk=data['card_id']).first() if data.get('card_id') else \
            cards.order_by('-is_default', '-created_at').first()
        if card is None:
            return error_response(_("Card not found"), status.HTTP_404_NOT_FOUND, 'card_not_found')
        txn = self.service.charge_card(
            card, data['amount'], reference=data.get('reference'), metadata=data.get('metadata'),
            fee_bearer=data.get('fee_bearer'), description=data.get('description'), **request_context(request),
        )
        txn.refresh_from_db()
        code = status.HTTP_200_OK if txn.is_successful else status.HTTP_202_ACCEPTED
        return Response(TransactionDetailSerializer(txn).data, status=code)

    # ------------------------------------------------------------------
    # Withdrawals
    # ------------------------------------------------------------------

    @action(detail=True, methods=['post'])
    def withdraw(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(WithdrawSerializer)
        self.check_pin(wallet, data.get('pin'))
        accounts = BankAccount.objects.filter(wallet=wallet, is_active=True).select_related('bank')
        bank_account = accounts.filter(pk=data['bank_account_id']).first() if data.get('bank_account_id') else \
            accounts.order_by('-is_default', '-created_at').first()
        if bank_account is None:
            return error_response(_("Bank account not found"), status.HTTP_404_NOT_FOUND, 'bank_account_not_found')

        txn, transfer = self.service.withdraw_to_bank(
            wallet, data['amount'], bank_account, reason=data.get('description'), metadata=data.get('metadata'),
            reference=data.get('reference'), fee_bearer=data.get('fee_bearer'), **request_context(request),
        )
        return Response(self._withdrawal_payload(txn), status=self._withdrawal_status(txn))

    @action(detail=True, methods=['post'], url_path='finalize-withdrawal')
    def finalize_withdrawal(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(FinalizeWithdrawalSerializer)
        txn = self._find_withdrawal(wallet, data)
        txn = self.service.finalize_withdrawal(txn, data['otp'])
        return Response(self._withdrawal_payload(txn), status=self._withdrawal_status(txn))

    @action(detail=True, methods=['post'], url_path='resend-otp')
    def resend_otp(self, request, pk=None):
        wallet = self.get_object()
        txn = self._find_withdrawal(wallet, self.validated(ResendOtpSerializer))
        self.service.resend_withdrawal_otp(txn)
        return Response({'detail': _("OTP resent")})

    @staticmethod
    def _find_withdrawal(wallet, data):
        queryset = Transaction.objects.filter(wallet=wallet, transaction_type=TRANSACTION_TYPE_WITHDRAWAL)
        if data.get('transaction_id'):
            queryset = queryset.filter(pk=data['transaction_id'])
        elif data.get('reference'):
            queryset = queryset.filter(reference=data['reference'])
        else:
            queryset = queryset.filter(paystack_transfer_code=data['transfer_code'])
        return queryset.get()

    @staticmethod
    def _withdrawal_payload(txn):
        if txn.is_successful:
            state, message = 'success', _("Withdrawal completed")
        elif txn.requires_otp:
            state, message = 'pending_otp', _("Enter the OTP to complete the withdrawal")
        elif txn.is_pending:
            state, message = 'processing', _("Withdrawal is being processed")
        else:
            state, message = 'failed', txn.failed_reason or _("Withdrawal failed")
        return {'status': state, 'message': str(message), 'transaction': TransactionDetailSerializer(txn).data}

    @staticmethod
    def _withdrawal_status(txn):
        if txn.is_successful:
            return status.HTTP_200_OK
        if txn.is_pending:
            return status.HTTP_202_ACCEPTED
        return status.HTTP_400_BAD_REQUEST

    # ------------------------------------------------------------------
    # Transfers & payments
    # ------------------------------------------------------------------

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(TransferSerializer)
        self.check_pin(wallet, data.get('pin'))
        txn = self.service.transfer(
            wallet, data['recipient'], data['amount'], description=data.get('description'),
            metadata=data.get('metadata'), reference=data.get('reference'), fee_bearer=data.get('fee_bearer'),
            lookup=data.get('recipient_type'), **request_context(request),
        )
        return Response(TransactionDetailSerializer(txn).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(PaySerializer)
        self.check_pin(wallet, data.get('pin'))
        txn = self.service.pay(
            wallet, data['amount'], merchant_wallet=data.get('merchant') or None,
            description=data.get('description'), reference=data.get('reference'), metadata=data.get('metadata'),
            fee_bearer=data.get('fee_bearer'), escrow=data.get('escrow', False), **request_context(request),
        )
        return Response(TransactionDetailSerializer(txn).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def lookup(self, request):
        if not is_feature_enabled('RECIPIENT_LOOKUP'):
            raise FeatureDisabled()
        data = self.validated(RecipientLookupSerializer, data=request.query_params)
        service = self.service
        recipient = service.resolve_recipient(data['recipient'], data.get('recipient_type'))
        return Response(service.describe_recipient(recipient))

    # ------------------------------------------------------------------
    # PIN
    # ------------------------------------------------------------------

    @action(detail=True, methods=['post'], url_path='set-pin')
    def set_pin(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(SetPinSerializer)
        if wallet.has_pin:
            if not data.get('current_pin'):
                raise PinRequired(_("Provide current_pin to change your PIN"))
            wallet.verify_pin(data['current_pin'])
        wallet.set_pin(data['pin'])
        return Response({'detail': _("PIN saved"), 'has_pin': True})

    # ------------------------------------------------------------------
    # Dedicated virtual account & identity
    # ------------------------------------------------------------------

    @action(detail=True, methods=['get', 'post'], url_path='dedicated-account')
    def dedicated_account(self, request, pk=None):
        if not is_feature_enabled('DEDICATED_ACCOUNTS'):
            raise FeatureDisabled()
        wallet = self.get_object()
        service = self.service
        if request.method == 'POST':
            data = self.validated(DedicatedAccountSerializer)
            service.create_dedicated_account(wallet, preferred_bank=data.get('preferred_bank'))
            return Response(service.get_dedicated_account(wallet), status=status.HTTP_201_CREATED)
        if not wallet.dedicated_account_number:
            return error_response(_("No dedicated account yet"), status.HTTP_404_NOT_FOUND, 'no_dedicated_account')
        return Response(service.get_dedicated_account(wallet))

    @action(detail=True, methods=['post'], url_path='requery-dedicated-account')
    def requery_dedicated_account(self, request, pk=None):
        if not is_feature_enabled('DEDICATED_ACCOUNTS'):
            raise FeatureDisabled()
        self.service.requery_dedicated_account(self.get_object(), date=request.data.get('date'))
        return Response({'detail': _("Requery started; new transfers will arrive by webhook")})

    @action(detail=True, methods=['post'], url_path='validate-customer')
    def validate_customer(self, request, pk=None):
        wallet = self.get_object()
        data = self.validated(CustomerValidationSerializer)
        self.service.validate_customer(wallet, **data)
        return Response({'detail': _("Validation in progress")}, status=status.HTTP_202_ACCEPTED)

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'], url_path='fee-quote')
    def fee_quote(self, request):
        wallet = self.get_user_wallet()
        data = self.validated(FeeQuoteSerializer)
        result = get_fee_calculator(wallet).calculate(
            data['amount'], data['transaction_type'], data.get('payment_channel'), bearer=data.get('fee_bearer'),
        )
        return Response(result.to_dict())


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
