"""Shared API plumbing: permissions, error mapping, pagination, PIN checks."""
import logging

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.utils.module_loading import import_string
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from wallet.apis import protection
from wallet.conf import is_feature_enabled, wallet_settings
from wallet.exceptions import FeatureDisabled, PaystackAPIError, PinRequired, WalletError, WalletNotFound
from wallet.models import IdempotencyRecord, Wallet

logger = logging.getLogger('wallet')


def get_client_ip(request):
    if wallet_settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def request_context(request):
    return {'ip_address': get_client_ip(request), 'user_agent': request.META.get('HTTP_USER_AGENT', '')}


def error_response(message, status_code, code=None, **extra):
    payload = {'detail': str(message)}
    if code:
        payload['code'] = code
    payload.update(extra)
    return Response(payload, status=status_code)


class WalletPagination(PageNumberPagination):
    page_size_query_param = 'page_size'

    @property
    def page_size(self):
        return int(wallet_settings.API_PAGE_SIZE)

    @property
    def max_page_size(self):
        return int(wallet_settings.API_MAX_PAGE_SIZE)


class IsStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)


class WalletAPIMixin:
    """
    Mixin for every wallet viewset.

    * permissions come from ``WALLET_API_PERMISSION_CLASSES``
    * :class:`~wallet.exceptions.WalletError` subclasses become JSON errors with
      the right HTTP status (Paystack failures -> 502)
    * ``feature`` switches a viewset off with ``WALLET_ENABLE_<FEATURE>=False``
    * ``throttle_scopes`` maps actions to ``WALLET_THROTTLE_RATES`` scopes
    * ``idempotent_actions`` honour the ``Idempotency-Key`` header
    """

    pagination_class = WalletPagination
    feature = None
    staff_actions = ()
    throttle_scopes = {}
    idempotent_actions = ()

    def get_permissions(self):
        if self.action in self.staff_actions:
            return [permissions.IsAuthenticated(), IsStaff()]
        classes = [import_string(path) if isinstance(path, str) else path
                   for path in wallet_settings.API_PERMISSION_CLASSES]
        return [permission() for permission in classes]

    def get_throttles(self):
        throttles = list(super().get_throttles())
        scope = self.throttle_scopes.get(getattr(self, 'action', None))
        if scope:
            throttles.append(protection.WalletRateThrottle(scope))
        return throttles

    def initial(self, request, *args, **kwargs):
        self._idempotency_record = None
        super().initial(request, *args, **kwargs)
        if self.feature and not is_feature_enabled(self.feature):
            raise FeatureDisabled()
        if self.action in self.idempotent_actions:
            self._idempotency_record = protection.begin(request)

    def finalize_response(self, request, response, *args, **kwargs):
        record = getattr(self, '_idempotency_record', None)
        if record is not None:
            self._idempotency_record = None
            protection.finish(record, response)
        return super().finalize_response(request, response, *args, **kwargs)

    def handle_exception(self, exc):
        try:
            return self._handle_exception(exc)
        except BaseException:
            # Unhandled error: DRF re-raises and never calls finalize_response, so release the
            # idempotency key here or every retry would be refused as "in progress".
            record = getattr(self, '_idempotency_record', None)
            if record is not None:
                self._idempotency_record = None
                IdempotencyRecord.objects.filter(pk=record.pk).delete()
            raise

    def _handle_exception(self, exc):
        if isinstance(exc, protection.IdempotentReplay):
            return Response(exc.record.response_body, status=exc.record.response_status,
                            headers={'Idempotent-Replayed': 'true'})
        if isinstance(exc, PaystackAPIError):
            logger.warning("Paystack error in %s: %s", type(self).__name__, exc)
            detail = exc.paystack_message if exc.is_definitive and exc.paystack_message else \
                'Payment provider error. Please try again.'
            return error_response(detail, exc.http_status, exc.code)
        if isinstance(exc, WalletError):
            return Response(exc.as_dict(), status=exc.http_status)
        if isinstance(exc, DjangoValidationError):
            return Response({'detail': exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, ObjectDoesNotExist):
            return error_response('Not found.', status.HTTP_404_NOT_FOUND, 'not_found')
        return super().handle_exception(exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_user_wallet(self, create=True):
        wallet = Wallet.objects.select_related('user').filter(user=self.request.user).first()
        if wallet is None and create:
            from wallet.services.wallet_service import WalletService
            wallet = WalletService().get_wallet(self.request.user)
        if wallet is None:
            raise WalletNotFound()
        return wallet

    def check_pin(self, wallet, pin):
        """Enforce the transaction PIN when ``WALLET_REQUIRE_TRANSACTION_PIN`` is on."""
        if not wallet_settings.REQUIRE_TRANSACTION_PIN:
            return
        if not pin:
            raise PinRequired()
        wallet.verify_pin(pin)

    def validated(self, serializer_class, data=None):
        serializer = serializer_class(data=self.request.data if data is None else data,
                                      context=self.get_serializer_context())
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)
        return serializer.validated_data

    def paginated(self, queryset, serializer_class):
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(serializer_class(page, many=True, context=self.get_serializer_context()).data)
        return Response(serializer_class(queryset, many=True, context=self.get_serializer_context()).data)
