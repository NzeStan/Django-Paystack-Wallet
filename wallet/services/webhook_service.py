import json
import logging
import hmac
import hashlib
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.models import WebhookEvent, WebhookEndpoint, WebhookDeliveryAttempt
from wallet.exceptions import InvalidWebhookSignature
from wallet.settings import get_wallet_setting
from wallet.services.transaction_service import TransactionService
from wallet.services.settlement_service import SettlementService


logger = logging.getLogger(__name__)


class WebhookService:
    """
    Service for handling and processing webhook events
    """
    def __init__(self):
        self.transaction_service = TransactionService()
        self.settlement_service = SettlementService()
    
    def verify_paystack_webhook_signature(self, signature, payload_bytes):
        """
        Verify that a webhook came from Paystack
        
        Args:
            signature (str): X-Paystack-Signature header value
            payload_bytes (bytes): Raw request body
            
        Returns:
            bool: True if signature is valid
            
        Raises:
            InvalidWebhookSignature: If the signature is invalid
        """
        secret_key = get_wallet_setting('PAYSTACK_SECRET_KEY')
        
        computed_hmac = hmac.new(
            key=secret_key.encode('utf-8'),
            msg=payload_bytes,
            digestmod=hashlib.sha512
        ).hexdigest()
        
        if not hmac.compare_digest(computed_hmac, signature):
            raise InvalidWebhookSignature()
        
        return True
    
    def process_paystack_webhook(self, payload_bytes, signature):
        """
        Process a webhook event from Paystack
        
        Args:
            payload_bytes (bytes): Raw request body
            signature (str): X-Paystack-Signature header value
            
        Returns:
            WebhookEvent: Created webhook event
            
        Raises:
            InvalidWebhookSignature: If the signature is invalid
            ValueError: If the payload is invalid
        """
        # Verify signature
        self.verify_paystack_webhook_signature(signature, payload_bytes)
        
        # Decode JSON payload
        try:
            payload = json.loads(payload_bytes.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid webhook payload: {str(e)}")
        
        # Extract event data
        event_type = payload.get('event')
        if not event_type:
            raise ValueError("Missing event type in webhook payload")
        
        data = payload.get('data', {})
        reference = data.get('reference') or data.get('transfer_code')
        
        # Create webhook event record
        webhook_event = WebhookEvent.objects.create(
            event_type=event_type,
            payload=payload,
            reference=reference,
            signature=signature,
            is_valid=True
        )
        
        # Process webhook event
        try:
            self._process_event(webhook_event)
        except Exception as e:
            logger.error(f"Error processing webhook event {webhook_event.id}: {str(e)}")
        
        return webhook_event
    
    def _process_event(self, webhook_event):
        """
        Process a webhook event
        
        Args:
            webhook_event (WebhookEvent): Webhook event to process
            
        Returns:
            bool: True if processed successfully
        """
        event_type = webhook_event.event_type
        data = webhook_event.payload.get('data', {})
        
        # Try to process with transaction service
        transaction_processed = self.transaction_service.process_paystack_webhook(event_type, data)
        
        # Try to process with settlement service
        settlement_processed = self.settlement_service.process_paystack_webhook(event_type, data)
        
        # Mark as processed if either service handled it
        processed = transaction_processed or settlement_processed
        
        if processed:
            webhook_event.processed = True
            webhook_event.processed_at = timezone.now()
            webhook_event.save(update_fields=['processed', 'processed_at'])
        
        # Forward event to custom webhook endpoints
        self._forward_to_endpoints(webhook_event)
        
        return processed
    
    def _forward_to_endpoints(self, webhook_event):
        """
        Forward a webhook event to custom endpoints
        
        Args:
            webhook_event (WebhookEvent): Webhook event to forward
            
        Returns:
            int: Number of successful deliveries
        """
        import requests
        import json
        import hmac
        import hashlib
        
        # Find all active endpoints
        endpoints = WebhookEndpoint.objects.filter(is_active=True)
        
        # Filter by event type using Python (database-agnostic approach)
        filtered_endpoints = []
        for endpoint in endpoints:
            if endpoint.event_types:
                # Check if the event type is in the array
                if isinstance(endpoint.event_types, list):
                    if webhook_event.event_type in endpoint.event_types:
                        filtered_endpoints.append(endpoint)
                elif isinstance(endpoint.event_types, str):
                    # If it's stored as JSON string
                    try:
                        event_types_list = json.loads(endpoint.event_types)
                        if webhook_event.event_type in event_types_list:
                            filtered_endpoints.append(endpoint)
                    except (json.JSONDecodeError, TypeError):
                        # Fallback: treat as single event type
                        if endpoint.event_types == webhook_event.event_type:
                            filtered_endpoints.append(endpoint)
            else:
                # If no specific event types configured, include all endpoints
                filtered_endpoints.append(endpoint)
        
        success_count = 0
        
        for endpoint in filtered_endpoints:
            try:
                # Prepare payload
                payload = {
                    'event': webhook_event.event_type,
                    'data': webhook_event.payload.get('data', {}),
                    'reference': webhook_event.reference,
                    'timestamp': webhook_event.created_at.isoformat()
                }
                
                # Prepare headers
                headers = dict(endpoint.headers or {})
                headers['Content-Type'] = 'application/json'
                
                # Add signature if secret is configured
                if endpoint.secret:
                    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
                    signature = hmac.new(
                        key=endpoint.secret.encode('utf-8'),
                        msg=payload_bytes,
                        digestmod=hashlib.sha256
                    ).hexdigest()
                    
                    headers['X-Webhook-Signature'] = f'sha256={signature}'
                
                # Create delivery attempt record
                attempt = WebhookDeliveryAttempt.objects.create(
                    webhook_event=webhook_event,
                    webhook_endpoint=endpoint,
                    request_data={
                        'url': endpoint.url,
                        'headers': headers,
                        'payload': payload
                    },
                    attempt_number=1
                )
                
                # Deliver webhook
                try:
                    response = requests.post(
                        url=endpoint.url,
                        json=payload,
                        headers=headers,
                        timeout=30,  # Increased timeout for better reliability
                        verify=True  # Verify SSL certificates
                    )
                    
                    # Record response
                    attempt.response_code = response.status_code
                    attempt.response_body = response.text[:1000]  # Limit response body size
                    attempt.is_success = 200 <= response.status_code < 300
                    
                    if attempt.is_success:
                        success_count += 1
                        logger.info(f"Successfully delivered webhook to {endpoint.url} for event {webhook_event.event_type}")
                    else:
                        logger.warning(f"Webhook delivery failed to {endpoint.url}: HTTP {response.status_code}")
                    
                    attempt.save()
                    
                except requests.Timeout:
                    # Handle timeout specifically
                    attempt.response_body = "Request timeout"
                    attempt.is_success = False
                    attempt.save()
                    logger.error(f"Webhook delivery timeout to {endpoint.url}")
                    
                except requests.ConnectionError:
                    # Handle connection errors
                    attempt.response_body = "Connection error"
                    attempt.is_success = False
                    attempt.save()
                    logger.error(f"Webhook delivery connection error to {endpoint.url}")
                    
                except requests.RequestException as e:
                    # Handle other request errors
                    attempt.response_body = str(e)[:1000]
                    attempt.is_success = False
                    attempt.save()
                    logger.error(f"Webhook delivery error to {endpoint.url}: {str(e)}")
                    
            except Exception as e:
                # Handle any other unexpected errors
                logger.error(f"Unexpected error processing webhook endpoint {endpoint.url}: {str(e)}", exc_info=True)
                
                # Try to create a failed attempt record
                try:
                    WebhookDeliveryAttempt.objects.create(
                        webhook_event=webhook_event,
                        webhook_endpoint=endpoint,
                        request_data={'error': str(e)},
                        attempt_number=1,
                        response_body=f"Processing error: {str(e)}",
                        is_success=False
                    )
                except Exception:
                    # If we can't even create the attempt record, just log it
                    logger.error(f"Failed to create delivery attempt record for {endpoint.url}")
        
        logger.info(f"Webhook forwarding completed: {success_count}/{len(filtered_endpoints)} successful deliveries")
        return success_count
    
    def retry_failed_delivery(self, delivery_attempt):
        """
        Retry a failed webhook delivery
        
        Args:
            delivery_attempt (WebhookDeliveryAttempt): Failed delivery attempt
            
        Returns:
            bool: True if delivery successful
        """
        import requests
        
        # Check if max retries exceeded
        endpoint = delivery_attempt.webhook_endpoint
        if delivery_attempt.attempt_number >= endpoint.retry_count:
            return False
        
        # Get request data
        request_data = delivery_attempt.request_data
        url = request_data.get('url')
        headers = request_data.get('headers', {})
        payload = request_data.get('payload', {})
        
        # Create new attempt record
        new_attempt = WebhookDeliveryAttempt.objects.create(
            webhook_event=delivery_attempt.webhook_event,
            webhook_endpoint=endpoint,
            request_data=request_data,
            attempt_number=delivery_attempt.attempt_number + 1
        )
        
        # Deliver webhook
        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=10
            )
            
            # Record response
            new_attempt.response_code = response.status_code
            new_attempt.response_body = response.text
            new_attempt.is_success = 200 <= response.status_code < 300
            new_attempt.save()
            
            return new_attempt.is_success
            
        except requests.RequestException as e:
            # Record failure
            new_attempt.response_body = str(e)
            new_attempt.is_success = False
            new_attempt.save()
            
            return False
    
    def retry_all_failed_deliveries(self):
        """
        Retry all failed webhook deliveries that haven't exceeded retry count
        
        Returns:
            int: Number of successful retries
        """
        from django.db.models import F, Q
        
        # Find failed delivery attempts
        query = Q(is_success=False) & Q(
            webhook_endpoint__retry_count__gt=F('attempt_number')
        )
        
        failed_attempts = WebhookDeliveryAttempt.objects.filter(query)
        
        success_count = 0
        
        for attempt in failed_attempts:
            success = self.retry_failed_delivery(attempt)
            if success:
                success_count += 1
        
        return success_count