"""
Webhook Service for Django Paystack Wallet

This module handles webhook events from Paystack and custom webhook endpoints.
It verifies webhook signatures, processes events, and forwards them to registered endpoints.
"""

import json
import logging
import hmac
import hashlib
import requests
from typing import Dict, List, Optional, Any
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db import transaction as db_transaction

from wallet.models import WebhookEvent, WebhookEndpoint, WebhookDeliveryAttempt
from wallet.exceptions import InvalidWebhookSignature
from wallet.settings import get_wallet_setting
from wallet.services.transaction_service import TransactionService
from wallet.services.settlement_service import SettlementService


logger = logging.getLogger(__name__)


class WebhookService:
    """
    Service for handling and processing webhook events from Paystack
    and forwarding to custom webhook endpoints.
    """
    
    def __init__(self):
        """Initialize webhook service with transaction and settlement services"""
        self.transaction_service = TransactionService()
        self.settlement_service = SettlementService()
        self._secret_key = get_wallet_setting('PAYSTACK_SECRET_KEY')
    
    # ==================== Signature Verification ====================
    
    def verify_paystack_webhook_signature(
        self, 
        signature: str, 
        payload_bytes: bytes
    ) -> bool:
        """
        Verify that a webhook came from Paystack using HMAC SHA512.
        
        Args:
            signature: X-Paystack-Signature header value
            payload_bytes: Raw request body
            
        Returns:
            True if signature is valid
            
        Raises:
            InvalidWebhookSignature: If the signature is invalid
        """
        if not signature:
            logger.error("Webhook signature is missing")
            raise InvalidWebhookSignature("Missing webhook signature")
        
        if not payload_bytes:
            logger.error("Webhook payload is empty")
            raise InvalidWebhookSignature("Empty webhook payload")
        
        # Compute HMAC SHA512
        computed_hmac = hmac.new(
            key=self._secret_key.encode('utf-8'),
            msg=payload_bytes,
            digestmod=hashlib.sha512
        ).hexdigest()
        
        # Compare signatures using constant-time comparison
        if not hmac.compare_digest(computed_hmac, signature):
            logger.error(
                "Invalid webhook signature received. "
                f"Expected: {computed_hmac[:10]}..., Got: {signature[:10]}..."
            )
            raise InvalidWebhookSignature("Invalid webhook signature")
        
        logger.debug("Webhook signature verified successfully")
        return True
    
    # ==================== Webhook Processing ====================
    
    @db_transaction.atomic
    def process_paystack_webhook(
        self, 
        payload_bytes: bytes, 
        signature: str
    ) -> WebhookEvent:
        """
        Process a webhook event from Paystack.
        
        This method:
        1. Verifies the webhook signature
        2. Parses the JSON payload
        3. Creates a WebhookEvent record
        4. Processes the event based on event type
        5. Forwards the event to custom endpoints
        
        Args:
            payload_bytes: Raw request body
            signature: X-Paystack-Signature header value
            
        Returns:
            Created WebhookEvent instance
            
        Raises:
            InvalidWebhookSignature: If the signature is invalid
            ValueError: If the payload is invalid
        """
        # Verify signature first
        self.verify_paystack_webhook_signature(signature, payload_bytes)
        
        # Decode JSON payload
        try:
            payload = json.loads(payload_bytes.decode('utf-8'))
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode webhook payload: {str(e)}")
            raise ValueError(f"Invalid webhook payload encoding: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse webhook JSON: {str(e)}")
            raise ValueError(f"Invalid webhook JSON payload: {str(e)}")
        
        # Extract event data
        event_type = payload.get('event')
        if not event_type:
            logger.error("Webhook payload missing event type")
            raise ValueError("Missing event type in webhook payload")
        
        data = payload.get('data', {})
        reference = data.get('reference') or data.get('transfer_code') or data.get('id')
        
        logger.info(
            f"Received webhook event: type={event_type}, "
            f"reference={reference}"
        )
        
        # Create webhook event record
        webhook_event = WebhookEvent.objects.create(
            event_type=event_type,
            payload=payload,
            reference=reference,
            signature=signature,
            is_valid=True
        )
        
        logger.info(f"Created webhook event record: id={webhook_event.id}")
        
        # Process webhook event (outside the transaction to prevent rollback issues)
        try:
            self._process_event(webhook_event)
        except Exception as e:
            logger.error(
                f"Error processing webhook event {webhook_event.id}: {str(e)}",
                exc_info=True
            )
            # Don't re-raise - we've already saved the webhook event
            # This allows us to retry processing later
        
        return webhook_event
    
    def _process_event(self, webhook_event: WebhookEvent) -> bool:
        """
        Process a webhook event by delegating to appropriate service.
        
        Args:
            webhook_event: Webhook event to process
            
        Returns:
            True if processed successfully, False otherwise
        """
        event_type = webhook_event.event_type
        data = webhook_event.payload.get('data', {})
        
        logger.info(
            f"Processing webhook event {webhook_event.id}: "
            f"type={event_type}"
        )
        
        processed = False
        
        # Try to process with transaction service (charge events)
        try:
            transaction_processed = self.transaction_service.process_paystack_webhook(
                event_type, 
                data
            )
            if transaction_processed:
                processed = True
                logger.info(
                    f"Webhook event {webhook_event.id} processed by TransactionService"
                )
        except Exception as e:
            logger.error(
                f"Error in TransactionService.process_paystack_webhook: {str(e)}",
                exc_info=True
            )
        
        # Try to process with settlement service (transfer events)
        try:
            settlement_processed = self.settlement_service.process_paystack_webhook(
                event_type, 
                data
            )
            if settlement_processed:
                processed = True
                logger.info(
                    f"Webhook event {webhook_event.id} processed by SettlementService"
                )
        except Exception as e:
            logger.error(
                f"Error in SettlementService.process_paystack_webhook: {str(e)}",
                exc_info=True
            )
        
        # Mark as processed if either service handled it
        if processed:
            webhook_event.processed = True
            webhook_event.processed_at = timezone.now()
            webhook_event.save(update_fields=['processed', 'processed_at'])
            logger.info(f"Webhook event {webhook_event.id} marked as processed")
        else:
            logger.warning(
                f"Webhook event {webhook_event.id} was not processed by any service. "
                f"Event type: {event_type}"
            )
        
        # Forward event to custom webhook endpoints
        try:
            self._forward_to_endpoints(webhook_event)
        except Exception as e:
            logger.error(
                f"Error forwarding webhook event {webhook_event.id}: {str(e)}",
                exc_info=True
            )
        
        return processed
    
    # ==================== Webhook Forwarding ====================
    
    def _forward_to_endpoints(self, webhook_event: WebhookEvent) -> None:
        """
        Forward a webhook event to custom webhook endpoints.
        
        Args:
            webhook_event: Webhook event to forward
        """
        # Get all active webhook endpoints
        endpoints = WebhookEndpoint.objects.filter(is_active=True)
        
        if not endpoints.exists():
            logger.debug("No active webhook endpoints to forward to")
            return
        
        logger.info(
            f"Forwarding webhook event {webhook_event.id} to "
            f"{endpoints.count()} endpoints"
        )
        
        for endpoint in endpoints:
            try:
                self.forward_webhook_to_endpoint(webhook_event, endpoint)
            except Exception as e:
                logger.error(
                    f"Error forwarding webhook {webhook_event.id} to "
                    f"endpoint {endpoint.id}: {str(e)}",
                    exc_info=True
                )
    
    def forward_webhook_to_endpoint(
        self, 
        webhook_event: WebhookEvent, 
        endpoint: WebhookEndpoint
    ) -> WebhookDeliveryAttempt:
        """
        Forward a webhook event to a specific endpoint.
        
        Args:
            webhook_event: Webhook event to forward
            endpoint: Webhook endpoint to forward to
            
        Returns:
            WebhookDeliveryAttempt instance
        """
        # Get the latest attempt number for this event and endpoint
        latest_attempt = WebhookDeliveryAttempt.objects.filter(
            webhook_event=webhook_event,
            webhook_endpoint=endpoint
        ).order_by('-attempt_number').first()
        
        attempt_number = (latest_attempt.attempt_number + 1) if latest_attempt else 1
        
        logger.info(
            f"Forwarding webhook {webhook_event.id} to {endpoint.url} "
            f"(attempt {attempt_number})"
        )
        
        # Prepare request data
        headers = {
            'Content-Type': 'application/json',
            'X-Webhook-Event-ID': str(webhook_event.id),
            'X-Webhook-Event-Type': webhook_event.event_type,
        }
        
        if webhook_event.signature:
            headers['X-Paystack-Signature'] = webhook_event.signature
        
        # Add custom headers from endpoint
        if endpoint.headers:
            headers.update(endpoint.headers)
        
        # Make HTTP request
        attempt = WebhookDeliveryAttempt.objects.create(
            webhook_event=webhook_event,
            webhook_endpoint=endpoint,
            attempt_number=attempt_number
        )
        
        try:
            response = requests.post(
                url=endpoint.url,
                json=webhook_event.payload,
                headers=headers,
                timeout=endpoint.timeout or 30
            )
            
            # Record response
            attempt.response_code = response.status_code
            attempt.response_body = response.text[:5000]  # Limit size
            attempt.is_success = 200 <= response.status_code < 300
            
            if attempt.is_success:
                logger.info(
                    f"Successfully forwarded webhook {webhook_event.id} to "
                    f"{endpoint.url}: status={response.status_code}"
                )
            else:
                logger.warning(
                    f"Failed to forward webhook {webhook_event.id} to "
                    f"{endpoint.url}: status={response.status_code}"
                )
            
        except requests.RequestException as e:
            logger.error(
                f"Request exception forwarding webhook {webhook_event.id} to "
                f"{endpoint.url}: {str(e)}",
                exc_info=True
            )
            attempt.response_body = str(e)[:5000]
            attempt.is_success = False
        except Exception as e:
            logger.error(
                f"Unexpected error forwarding webhook {webhook_event.id} to "
                f"{endpoint.url}: {str(e)}",
                exc_info=True
            )
            attempt.response_body = str(e)[:5000]
            attempt.is_success = False
        
        attempt.save()
        return attempt
    
    # ==================== Retry Logic ====================
    
    def retry_failed_webhook_delivery(
        self, 
        delivery_attempt: WebhookDeliveryAttempt
    ) -> WebhookDeliveryAttempt:
        """
        Retry a failed webhook delivery.
        
        Args:
            delivery_attempt: Failed delivery attempt to retry
            
        Returns:
            New WebhookDeliveryAttempt instance
            
        Raises:
            ValueError: If the delivery was successful or max retries exceeded
        """
        if delivery_attempt.is_success:
            raise ValueError("Cannot retry successful delivery")
        
        endpoint = delivery_attempt.webhook_endpoint
        if delivery_attempt.attempt_number >= endpoint.retry_count:
            raise ValueError("Maximum retry attempts exceeded")
        
        logger.info(
            f"Retrying failed webhook delivery {delivery_attempt.id}"
        )
        
        return self.forward_webhook_to_endpoint(
            delivery_attempt.webhook_event,
            endpoint
        )
    
    def retry_all_failed_deliveries(
        self, 
        max_attempts: Optional[int] = None
    ) -> int:
        """
        Retry all failed webhook deliveries that haven't exceeded retry count.
        
        Args:
            max_attempts: Maximum number of deliveries to retry (None for all)
            
        Returns:
            Number of deliveries retried
        """
        logger.info("Starting bulk retry of failed webhook deliveries")
        
        # Get failed deliveries that can be retried
        failed_deliveries = WebhookDeliveryAttempt.objects.filter(
            is_success=False
        ).select_related('webhook_event', 'webhook_endpoint')
        
        if max_attempts:
            failed_deliveries = failed_deliveries[:max_attempts]
        
        retried_count = 0
        
        for delivery in failed_deliveries:
            try:
                # Check if we can retry
                if delivery.attempt_number >= delivery.webhook_endpoint.retry_count:
                    continue
                
                self.retry_failed_webhook_delivery(delivery)
                retried_count += 1
                
            except Exception as e:
                logger.error(
                    f"Error retrying delivery {delivery.id}: {str(e)}",
                    exc_info=True
                )
        
        logger.info(f"Retried {retried_count} failed webhook deliveries")
        return retried_count
    
    # ==================== Webhook Endpoint Management ====================
    
    def register_webhook_endpoint(
        self,
        name: str,
        url: str,
        wallets: Optional[List] = None,
        headers: Optional[Dict[str, str]] = None,
        retry_count: int = 3,
        timeout: int = 30
    ) -> WebhookEndpoint:
        """
        Register a new webhook endpoint.
        
        Args:
            name: Endpoint name
            url: Endpoint URL
            wallets: Optional list of wallet instances to filter events
            headers: Optional custom headers to include
            retry_count: Number of retry attempts on failure
            timeout: Request timeout in seconds
            
        Returns:
            Created WebhookEndpoint instance
        """
        logger.info(f"Registering webhook endpoint: {name} -> {url}")
        
        endpoint = WebhookEndpoint.objects.create(
            name=name,
            url=url,
            headers=headers or {},
            retry_count=retry_count,
            timeout=timeout,
            is_active=True
        )
        
        if wallets:
            endpoint.wallets.set(wallets)
        
        logger.info(f"Registered webhook endpoint: id={endpoint.id}")
        return endpoint
    
    def get_webhook_event(self, event_id: str) -> Optional[WebhookEvent]:
        """
        Get a webhook event by ID.
        
        Args:
            event_id: Webhook event ID
            
        Returns:
            WebhookEvent instance or None if not found
        """
        try:
            return WebhookEvent.objects.get(id=event_id)
        except WebhookEvent.DoesNotExist:
            logger.warning(f"Webhook event not found: {event_id}")
            return None
    
    def list_webhook_events(
        self,
        event_type: Optional[str] = None,
        processed: Optional[bool] = None,
        limit: int = 100
    ) -> List[WebhookEvent]:
        """
        List webhook events with optional filtering.
        
        Args:
            event_type: Filter by event type
            processed: Filter by processed status
            limit: Maximum number of events to return
            
        Returns:
            List of WebhookEvent instances
        """
        queryset = WebhookEvent.objects.all()
        
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        
        if processed is not None:
            queryset = queryset.filter(processed=processed)
        
        return list(queryset.order_by('-created_at')[:limit])
    
    def reprocess_webhook_event(self, event_id: str) -> bool:
        """
        Reprocess a webhook event.
        
        Args:
            event_id: Webhook event ID
            
        Returns:
            True if reprocessed successfully
            
        Raises:
            ValueError: If event not found
        """
        webhook_event = self.get_webhook_event(event_id)
        if not webhook_event:
            raise ValueError(f"Webhook event not found: {event_id}")
        
        logger.info(f"Reprocessing webhook event {event_id}")
        
        # Reset processed status
        webhook_event.processed = False
        webhook_event.processed_at = None
        webhook_event.save(update_fields=['processed', 'processed_at'])
        
        # Process the event
        return self._process_event(webhook_event)