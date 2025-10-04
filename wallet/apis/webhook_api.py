from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from wallet.services.webhook_service import WebhookService


@csrf_exempt
@api_view(['POST'])
@permission_classes([])  # No permission required for webhook
def paystack_webhook(request):
    """
    Handle webhook events from Paystack
    """
    webhook_service = WebhookService()
    
    try:
        # Get request data
        payload_bytes = request.body
        signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE')
        
        if not signature:
            return Response(
                {"detail": _("Missing signature header")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Process webhook
        webhook_event = webhook_service.process_paystack_webhook(payload_bytes, signature)
        
        # Return success
        return Response(
            {"status": "success", "event_id": str(webhook_event.id)},
            status=status.HTTP_200_OK
        )
    except Exception as e:
        # Always return 200 OK to Paystack even if processing fails
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error processing Paystack webhook: {str(e)}")
        
        return Response(
            {"status": "success", "detail": "Event received but not processed"},
            status=status.HTTP_200_OK
        )