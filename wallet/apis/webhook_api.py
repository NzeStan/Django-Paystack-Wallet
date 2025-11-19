"""
Webhook API for Django Paystack Wallet

This module provides API endpoints for handling Paystack webhooks
and managing custom webhook endpoints.
"""

import logging
from rest_framework import status, viewsets, permissions
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db.models import Q

from wallet.models import WebhookEvent, WebhookEndpoint, WebhookDeliveryAttempt
from wallet.serializers.webhook_serializer import (
    WebhookEventSerializer,
    WebhookEndpointSerializer,
    WebhookDeliveryAttemptSerializer
)
from wallet.services.webhook_service import WebhookService
from wallet.exceptions import InvalidWebhookSignature
from wallet.permissions import IsWebhookEndpointOwner


logger = logging.getLogger(__name__)


# ==================== Paystack Webhook Handler ====================

@csrf_exempt
@api_view(['POST'])
@permission_classes([])  # No authentication required for webhooks
def paystack_webhook(request):
    """
    Handle webhook events from Paystack.
    
    This endpoint:
    1. Receives webhook events from Paystack
    2. Verifies the webhook signature
    3. Processes the event
    4. Returns success to Paystack
    
    IMPORTANT: Always returns 200 OK to Paystack to prevent retries,
    even if processing fails. Failed events can be reprocessed later.
    
    Request Headers:
        X-Paystack-Signature: HMAC SHA512 signature of the request body
    
    Request Body:
        JSON payload from Paystack containing event data
    
    Response:
        200 OK: Event received successfully
        400 Bad Request: Missing signature or invalid payload
    """
    webhook_service = WebhookService()
    
    try:
        # Get request data
        payload_bytes = request.body
        signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE')
        
        # Validate signature header
        if not signature:
            logger.warning(
                f"Webhook received without signature from IP: "
                f"{request.META.get('REMOTE_ADDR')}"
            )
            return Response(
                {
                    "status": "error",
                    "message": _("Missing signature header")
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Process webhook
        webhook_event = webhook_service.process_paystack_webhook(
            payload_bytes, 
            signature
        )
        
        logger.info(
            f"Webhook processed successfully: "
            f"event_id={webhook_event.id}, "
            f"event_type={webhook_event.event_type}, "
            f"reference={webhook_event.reference}"
        )
        
        # Return success response
        return Response(
            {
                "status": "success",
                "message": _("Webhook received and queued for processing"),
                "event_id": str(webhook_event.id),
                "event_type": webhook_event.event_type
            },
            status=status.HTTP_200_OK
        )
        
    except InvalidWebhookSignature as e:
        # Log security issue but still return 200 to avoid retries
        logger.error(
            f"Invalid webhook signature from IP: "
            f"{request.META.get('REMOTE_ADDR')}",
            exc_info=True
        )
        return Response(
            {
                "status": "error",
                "message": _("Invalid webhook signature")
            },
            status=status.HTTP_400_BAD_REQUEST
        )
        
    except ValueError as e:
        # Invalid payload format
        logger.error(
            f"Invalid webhook payload: {str(e)}",
            exc_info=True
        )
        # Return 200 to prevent Paystack retries for invalid data
        return Response(
            {
                "status": "error",
                "message": str(e)
            },
            status=status.HTTP_400_BAD_REQUEST
        )
        
    except Exception as e:
        # Log unexpected errors but return 200 to prevent retries
        logger.error(
            f"Unexpected error processing webhook: {str(e)}",
            exc_info=True
        )
        # Always return 200 OK to Paystack to prevent endless retries
        return Response(
            {
                "status": "success",
                "message": _("Event received but processing failed. Will retry later.")
            },
            status=status.HTTP_200_OK
        )


# ==================== Webhook Event ViewSet ====================

class WebhookEventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for webhook events.
    
    Provides read-only access to webhook events with filtering and reprocessing.
    """
    
    queryset = WebhookEvent.objects.all().order_by('-created_at')
    serializer_class = WebhookEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['event_type', 'processed', 'is_valid']
    search_fields = ['reference', 'event_type']
    ordering_fields = ['created_at', 'processed_at']
    
    def get_queryset(self):
        """
        Filter webhook events based on user permissions.
        
        Staff users can see all events.
        Regular users can only see events related to their wallets.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.is_staff:
            return queryset
        
        # Filter to events related to user's wallets
        user_wallets = user.wallets.all()
        return queryset.filter(
            Q(payload__data__metadata__wallet_id__in=[
                str(w.id) for w in user_wallets
            ]) |
            Q(payload__data__customer__email=user.email)
        ).distinct()
    
    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        """
        Reprocess a webhook event.
        
        This action allows staff users to manually reprocess failed webhook events.
        
        Request Body:
            None required
        
        Response:
            200 OK: Event reprocessed successfully
            403 Forbidden: User is not staff
            404 Not Found: Event not found
        """
        if not request.user.is_staff:
            return Response(
                {"detail": _("You do not have permission to reprocess webhook events")},
                status=status.HTTP_403_FORBIDDEN
            )
        
        webhook_event = self.get_object()
        webhook_service = WebhookService()
        
        try:
            success = webhook_service.reprocess_webhook_event(str(webhook_event.id))
            
            # Refresh from database
            webhook_event.refresh_from_db()
            serializer = self.get_serializer(webhook_event)
            
            return Response(
                {
                    "status": "success",
                    "message": _("Webhook event reprocessed successfully"),
                    "processed": success,
                    "event": serializer.data
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(
                f"Error reprocessing webhook event {webhook_event.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {
                    "status": "error",
                    "message": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== Webhook Endpoint ViewSet ====================

class WebhookEndpointViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing custom webhook endpoints.
    
    Allows users to register, update, and manage their webhook endpoints.
    """
    
    queryset = WebhookEndpoint.objects.all().order_by('-created_at')
    serializer_class = WebhookEndpointSerializer
    permission_classes = [permissions.IsAuthenticated, IsWebhookEndpointOwner]
    filterset_fields = ['is_active']
    search_fields = ['name', 'url']
    ordering_fields = ['created_at', 'name']
    
    def get_queryset(self):
        """
        Filter webhook endpoints based on user permissions.
        
        Staff users can see all endpoints.
        Regular users can only see endpoints for their wallets.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.is_staff:
            return queryset
        
        # Filter to endpoints for user's wallets
        user_wallets = user.wallets.all()
        return queryset.filter(wallets__in=user_wallets).distinct()
    
    def perform_create(self, serializer):
        """
        Create a webhook endpoint.
        
        Automatically associates the endpoint with the user's wallets
        if not specified.
        """
        user = self.request.user
        
        # If no wallets specified, use all user's wallets
        if 'wallets' not in self.request.data or not self.request.data['wallets']:
            serializer.save()
            instance = serializer.instance
            instance.wallets.set(user.wallets.all())
        else:
            serializer.save()
        
        logger.info(
            f"Webhook endpoint created: id={serializer.instance.id}, "
            f"user={user.id}"
        )
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """
        Test a webhook endpoint by sending a test event.
        
        Request Body:
            test_payload (dict, optional): Custom test payload
        
        Response:
            200 OK: Test sent successfully
            404 Not Found: Endpoint not found
            500 Internal Server Error: Test failed
        """
        endpoint = self.get_object()
        webhook_service = WebhookService()
        
        # Create a test webhook event
        test_payload = request.data.get('test_payload', {
            "event": "test.event",
            "data": {
                "message": "This is a test webhook event",
                "timestamp": str(timezone.now())
            }
        })
        
        test_event = WebhookEvent.objects.create(
            event_type="test.event",
            payload=test_payload,
            reference="TEST",
            is_valid=True,
            processed=True
        )
        
        try:
            delivery_attempt = webhook_service.forward_webhook_to_endpoint(
                test_event,
                endpoint
            )
            
            serializer = WebhookDeliveryAttemptSerializer(delivery_attempt)
            
            return Response(
                {
                    "status": "success" if delivery_attempt.is_success else "failed",
                    "message": _(
                        "Test webhook sent successfully" 
                        if delivery_attempt.is_success 
                        else "Test webhook failed"
                    ),
                    "delivery_attempt": serializer.data
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(
                f"Error testing webhook endpoint {endpoint.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {
                    "status": "error",
                    "message": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """
        Toggle the active status of a webhook endpoint.
        
        Response:
            200 OK: Status toggled successfully
        """
        endpoint = self.get_object()
        endpoint.is_active = not endpoint.is_active
        endpoint.save(update_fields=['is_active'])
        
        serializer = self.get_serializer(endpoint)
        
        return Response(
            {
                "status": "success",
                "message": _(
                    "Webhook endpoint activated" 
                    if endpoint.is_active 
                    else "Webhook endpoint deactivated"
                ),
                "endpoint": serializer.data
            },
            status=status.HTTP_200_OK
        )


# ==================== Webhook Delivery Attempt ViewSet ====================

class WebhookDeliveryAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for webhook delivery attempts.
    
    Provides read-only access to delivery attempts with retry functionality.
    """
    
    queryset = WebhookDeliveryAttempt.objects.all().order_by('-created_at')
    serializer_class = WebhookDeliveryAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['is_success', 'response_code', 'attempt_number']
    search_fields = ['webhook_event__reference', 'webhook_endpoint__name']
    ordering_fields = ['created_at', 'attempt_number']
    
    def get_queryset(self):
        """
        Filter delivery attempts based on user permissions.
        
        Staff users can see all attempts.
        Regular users can only see attempts for their webhook endpoints.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.is_staff:
            return queryset
        
        # Filter to attempts for user's webhook endpoints
        user_wallets = user.wallets.all()
        return queryset.filter(
            webhook_endpoint__wallets__in=user_wallets
        ).distinct()
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retry a failed webhook delivery attempt.
        
        Response:
            200 OK: Retry successful
            400 Bad Request: Cannot retry (successful or max attempts exceeded)
            403 Forbidden: User is not staff
        """
        if not request.user.is_staff:
            return Response(
                {"detail": _("You do not have permission to retry webhook deliveries")},
                status=status.HTTP_403_FORBIDDEN
            )
        
        delivery_attempt = self.get_object()
        webhook_service = WebhookService()
        
        try:
            new_attempt = webhook_service.retry_failed_webhook_delivery(
                delivery_attempt
            )
            
            serializer = self.get_serializer(new_attempt)
            
            return Response(
                {
                    "status": "success",
                    "message": _("Webhook delivery retried successfully"),
                    "attempt": serializer.data
                },
                status=status.HTTP_200_OK
            )
            
        except ValueError as e:
            return Response(
                {
                    "status": "error",
                    "message": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(
                f"Error retrying delivery attempt {delivery_attempt.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {
                    "status": "error",
                    "message": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )