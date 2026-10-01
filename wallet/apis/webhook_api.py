"""
Paystack webhook receiver and (staff-only) webhook administration.

Point Paystack (Dashboard -> Settings -> API Keys & Webhooks) at::

    https://your-domain.com/<wallet-prefix>/webhook/
"""
import logging

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from wallet.apis.base import WalletPagination, get_client_ip
from wallet.exceptions import InvalidWebhookSignature, WalletError
from wallet.models import WebhookDeliveryAttempt, WebhookEndpoint, WebhookEvent
from wallet.serializers.webhook_serializer import (
    WebhookDeliveryAttemptSerializer,
    WebhookEndpointSerializer,
    WebhookEventSerializer,
)
from wallet.services.webhook_service import WebhookService

logger = logging.getLogger('wallet')


@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):
    """
    Receives Paystack events. Answers 200 for every authentic event (even if
    processing failed - it is stored and can be replayed) so Paystack does not
    retry forever; 401 for bad signatures; 400 for malformed payloads.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request, *args, **kwargs):
        signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE', '')
        try:
            event, created = WebhookService().handle_webhook(request.body, signature, get_client_ip(request))
        except InvalidWebhookSignature as exc:
            logger.warning("Rejected webhook from %s: %s", get_client_ip(request), exc)
            return Response({'status': 'error', 'detail': exc.message}, status=status.HTTP_401_UNAUTHORIZED)
        except ValueError as exc:
            return Response({'status': 'error', 'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': 'ok', 'event_id': str(event.pk), 'duplicate': not created})


paystack_webhook = PaystackWebhookView.as_view()


class WebhookEventViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = WalletPagination
    serializer_class = WebhookEventSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = WebhookEvent.objects.all()
        params = self.request.query_params
        if params.get('event_type'):
            queryset = queryset.filter(event_type=params['event_type'])
        if params.get('processed') in ('true', 'false'):
            queryset = queryset.filter(processed=params['processed'] == 'true')
        return queryset.order_by('-created_at')

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        event = self.get_object()
        ok = WebhookService().process_event(event)
        event.refresh_from_db()
        return Response(WebhookEventSerializer(event).data, status=200 if ok else 500)


class WebhookEndpointViewSet(viewsets.ModelViewSet):
    pagination_class = WalletPagination
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsAdminUser]
    queryset = WebhookEndpoint.objects.all().order_by('name')

    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        endpoint = self.get_object()
        event = WebhookEvent.objects.order_by('-created_at').first()
        if event is None:
            return Response({'detail': 'No webhook events to send yet'}, status=status.HTTP_400_BAD_REQUEST)
        attempt = WebhookService().forward_webhook_to_endpoint(event, endpoint)
        return Response(WebhookDeliveryAttemptSerializer(attempt).data)


class WebhookDeliveryAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = WalletPagination
    serializer_class = WebhookDeliveryAttemptSerializer
    permission_classes = [IsAdminUser]
    queryset = WebhookDeliveryAttempt.objects.select_related('webhook_event', 'webhook_endpoint').order_by(
        '-created_at')

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        try:
            attempt = WebhookService().retry_failed_webhook_delivery(self.get_object())
        except WalletError as exc:
            return Response(exc.as_dict(), status=status.HTTP_400_BAD_REQUEST)
        return Response(WebhookDeliveryAttemptSerializer(attempt).data)
