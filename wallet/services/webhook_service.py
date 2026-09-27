"""
Paystack webhook handling.

1. (optional) check the request comes from a Paystack IP
2. verify ``X-Paystack-Signature`` (HMAC-SHA512 of the raw body)
3. store the event - duplicates (Paystack retries) are detected by a hash of the body
4. dispatch to the built-in handler for the event (deposits, transfers, refunds, DVA, identity)
5. send the ``paystack_webhook_received`` signal - hook your own logic here for
   subscriptions, invoices, payment requests, disputes, ...
6. (optional) forward a signed copy to registered HTTP endpoints

Processing errors are recorded on the event and never turned into a non-200
response: the event is stored and can be replayed with
:meth:`WebhookService.reprocess_webhook_event`.
"""
import hashlib
import hmac
import json
import logging
from datetime import timedelta

import requests
from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone

from wallet.conf import wallet_settings
from wallet.constants import (
    WEBHOOK_EVENT_CHARGE_DISPUTE_CREATE,
    WEBHOOK_EVENT_CHARGE_DISPUTE_REMIND,
    WEBHOOK_EVENT_CHARGE_DISPUTE_RESOLVE,
    WEBHOOK_EVENT_CHARGE_FAILED,
    WEBHOOK_EVENT_CHARGE_SUCCESS,
    WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_FAILED,
    WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_SUCCESS,
    WEBHOOK_EVENT_DVA_ASSIGN_FAILED,
    WEBHOOK_EVENT_DVA_ASSIGN_SUCCESS,
    WEBHOOK_EVENT_REFUND_FAILED,
    WEBHOOK_EVENT_REFUND_PENDING,
    WEBHOOK_EVENT_REFUND_PROCESSED,
    WEBHOOK_EVENT_REFUND_PROCESSING,
    WEBHOOK_EVENT_TRANSFER_FAILED,
    WEBHOOK_EVENT_TRANSFER_REVERSED,
    WEBHOOK_EVENT_TRANSFER_SUCCESS,
)
from wallet.exceptions import InvalidWebhookSignature, WalletError
from wallet.models import Transaction, WebhookDeliveryAttempt, WebhookEndpoint, WebhookEvent
from wallet.paystack.client import verify_signature
from wallet.services.base import BaseService
from wallet.signals import dispute_event, paystack_webhook_received, send_on_commit

logger = logging.getLogger('wallet')


class WebhookService(BaseService):

    def __init__(self, paystack=None):
        super().__init__(paystack)
        self._handlers = {
            WEBHOOK_EVENT_CHARGE_SUCCESS: self._handle_charge,
            WEBHOOK_EVENT_CHARGE_FAILED: self._handle_charge,
            WEBHOOK_EVENT_TRANSFER_SUCCESS: self._handle_transfer,
            WEBHOOK_EVENT_TRANSFER_FAILED: self._handle_transfer,
            WEBHOOK_EVENT_TRANSFER_REVERSED: self._handle_transfer,
            WEBHOOK_EVENT_REFUND_PENDING: self._handle_refund,
            WEBHOOK_EVENT_REFUND_PROCESSING: self._handle_refund,
            WEBHOOK_EVENT_REFUND_PROCESSED: self._handle_refund,
            WEBHOOK_EVENT_REFUND_FAILED: self._handle_refund,
            WEBHOOK_EVENT_DVA_ASSIGN_SUCCESS: self._handle_dedicated_account,
            WEBHOOK_EVENT_DVA_ASSIGN_FAILED: self._handle_dedicated_account,
            WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_SUCCESS: self._handle_identification,
            WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_FAILED: self._handle_identification,
            WEBHOOK_EVENT_CHARGE_DISPUTE_CREATE: self._handle_dispute,
            WEBHOOK_EVENT_CHARGE_DISPUTE_REMIND: self._handle_dispute,
            WEBHOOK_EVENT_CHARGE_DISPUTE_RESOLVE: self._handle_dispute,
        }

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    @staticmethod
    def is_allowed_ip(ip_address):
        if not wallet_settings.WEBHOOK_VERIFY_IP:
            return True
        return ip_address in set(wallet_settings.WEBHOOK_ALLOWED_IPS or [])

    def verify_paystack_webhook_signature(self, signature, payload_bytes):
        if not signature:
            raise InvalidWebhookSignature("Missing webhook signature")
        if not payload_bytes:
            raise InvalidWebhookSignature("Empty webhook payload")
        if not verify_signature(payload_bytes, signature, self.paystack.secret_key):
            raise InvalidWebhookSignature()
        return True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle_webhook(self, payload_bytes, signature, ip_address=None):
        """
        Verify, store and process a webhook. Returns ``(event, created)``;
        ``created`` is False for a duplicate delivery.
        """
        if not self.is_allowed_ip(ip_address):
            raise InvalidWebhookSignature(f"Webhook from unexpected IP {ip_address}")
        self.verify_paystack_webhook_signature(signature, payload_bytes)

        try:
            payload = json.loads(payload_bytes.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid webhook payload: {exc}") from exc
        if not isinstance(payload, dict) or not payload.get('event'):
            raise ValueError("Missing event type in webhook payload")

        data = payload.get('data')
        reference = None
        if isinstance(data, dict):
            customer = data.get('customer') if isinstance(data.get('customer'), dict) else {}
            reference = (
                data.get('reference') or data.get('transfer_code') or data.get('transaction_reference')
                or customer.get('customer_code')
            )
        key = hashlib.sha256(payload_bytes).hexdigest()

        try:
            with db_transaction.atomic():
                event, created = WebhookEvent.objects.get_or_create(
                    idempotency_key=key,
                    defaults={
                        'event_type': payload['event'], 'payload': payload,
                        'reference': str(reference)[:150] if reference else None,
                        'signature': signature[:255], 'is_valid': True,
                    },
                )
        except IntegrityError:
            event, created = WebhookEvent.objects.get(idempotency_key=key), False

        if not created and event.processed:
            logger.info("Duplicate webhook %s ignored", event.pk)
            return event, False

        if wallet_settings.USE_CELERY:
            from wallet.tasks import process_webhook_event_task
            event_pk = str(event.pk)
            db_transaction.on_commit(lambda: process_webhook_event_task.delay(event_pk))
        else:
            self.process_event(event)
        return event, created

    # Backwards compatible entry point
    def process_paystack_webhook(self, payload_bytes, signature):
        event, _created = self.handle_webhook(payload_bytes, signature)
        return event

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process_event(self, event):
        """Run the built-in handler for ``event``. Never raises; errors are stored on the event."""
        data = event.data if isinstance(event.data, dict) else {}
        handler = self._handlers.get(event.event_type)
        handled = False
        error = ''
        event.processing_attempts += 1
        try:
            if handler is not None:
                result = handler(event.event_type, data, event)
                handled = result is not None
        except Exception as exc:  # recorded for replay; must not bubble up to Paystack
            logger.exception("Error processing webhook %s (%s)", event.pk, event.event_type)
            error = f"{type(exc).__name__}: {exc}"
            # The handler may have linked a transaction that was then rolled back
            if event.transaction_id and not Transaction.objects.filter(pk=event.transaction_id).exists():
                event.transaction = None

        event.processing_error = error
        event.processed = not error
        event.processed_at = timezone.now() if not error else None
        event.save(update_fields=['processed', 'processed_at', 'processing_error', 'processing_attempts',
                                  'transaction', 'updated_at'])

        if not error:
            send_on_commit(paystack_webhook_received, sender=WebhookEvent, event=event.event_type, data=data,
                           webhook_event=event, handled=handled)
            if wallet_settings.ENABLE_WEBHOOK_FORWARDING:
                self._forward(event)
        return not error

    def reprocess_webhook_event(self, event_id):
        event = WebhookEvent.objects.get(pk=event_id)
        return self.process_event(event)

    # ------------------------------------------------------------------
    # Built-in handlers
    # ------------------------------------------------------------------

    def _handle_charge(self, event_type, data, event):
        from wallet.services.deposit_service import DepositService

        if event_type == WEBHOOK_EVENT_CHARGE_FAILED and not data.get('status'):
            data = {**data, 'status': 'failed'}
        return DepositService(paystack=self.paystack).process_charge(data, webhook_event=event)

    def _handle_transfer(self, event_type, data, event):
        from wallet.services.withdrawal_service import WithdrawalService

        return WithdrawalService(paystack=self.paystack).process_transfer_event(event_type, data, webhook_event=event)

    def _handle_refund(self, event_type, data, event):
        from wallet.services.transaction_service import TransactionService

        return TransactionService(paystack=self.paystack).process_refund_event(event_type, data, webhook_event=event)

    def _handle_dedicated_account(self, event_type, data, event):
        from wallet.services.customer_service import CustomerService

        return CustomerService(paystack=self.paystack).process_dedicated_account_event(event_type, data)

    def _handle_identification(self, event_type, data, event):
        from wallet.services.customer_service import CustomerService

        return CustomerService(paystack=self.paystack).process_identification_event(event_type, data)

    def _handle_dispute(self, event_type, data, event):
        transaction_data = data.get('transaction') if isinstance(data.get('transaction'), dict) else {}
        reference = transaction_data.get('reference')
        txn = Transaction.objects.filter(reference=reference).first() if reference else None
        if txn is not None and event.transaction_id is None:
            event.transaction = txn
        send_on_commit(dispute_event, sender=WebhookEvent, event=event_type, data=data, transaction=txn)
        return txn or data

    # ------------------------------------------------------------------
    # Forwarding to your own endpoints
    # ------------------------------------------------------------------

    def _endpoints_for(self, event):
        endpoints = WebhookEndpoint.objects.filter(is_active=True).prefetch_related('wallets')
        wallet_id = event.transaction.wallet_id if event.transaction_id else None
        selected = []
        for endpoint in endpoints:
            if not endpoint.accepts(event.event_type):
                continue
            scoped = {w.pk for w in endpoint.wallets.all()}
            if scoped and wallet_id not in scoped:
                continue
            selected.append(endpoint)
        return selected

    def _forward(self, event):
        for endpoint in self._endpoints_for(event):
            if wallet_settings.USE_CELERY:
                from wallet.tasks import deliver_webhook_task
                event_pk, endpoint_pk = str(event.pk), str(endpoint.pk)
                db_transaction.on_commit(lambda e=event_pk, p=endpoint_pk: deliver_webhook_task.delay(e, p))
            else:
                try:
                    self.forward_webhook_to_endpoint(event, endpoint)
                except Exception:
                    logger.exception("Forwarding webhook %s to %s failed", event.pk, endpoint.url)

    @staticmethod
    def sign_payload(body, secret):
        return hmac.new((secret or '').encode('utf-8'), body, hashlib.sha512).hexdigest()

    def forward_webhook_to_endpoint(self, event, endpoint):
        attempt_number = WebhookDeliveryAttempt.objects.filter(
            webhook_event=event, webhook_endpoint=endpoint,
        ).count() + 1
        body = json.dumps(event.payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'django-paystack-wallet',
            'X-Wallet-Event': event.event_type,
            'X-Wallet-Event-Id': str(event.pk),
            'X-Wallet-Delivery-Attempt': str(attempt_number),
        }
        if endpoint.secret:
            headers['X-Wallet-Signature'] = self.sign_payload(body, endpoint.secret)
        headers.update({str(k): str(v) for k, v in (endpoint.headers or {}).items()})

        attempt = WebhookDeliveryAttempt(
            webhook_event=event, webhook_endpoint=endpoint, attempt_number=attempt_number,
            request_data={'url': endpoint.url, 'headers': {k: v for k, v in headers.items()
                                                           if k != 'X-Wallet-Signature'}},
        )
        try:
            response = requests.post(endpoint.url, data=body, headers=headers, timeout=endpoint.timeout or 10)
            attempt.response_code = response.status_code
            attempt.response_body = (response.text or '')[:5000]
            attempt.is_success = 200 <= response.status_code < 300
        except requests.RequestException as exc:
            attempt.response_body = str(exc)[:5000]
            attempt.is_success = False
        attempt.save()
        return attempt

    def retry_failed_webhook_delivery(self, delivery_attempt):
        if delivery_attempt.is_success:
            raise WalletError("Cannot retry a successful delivery")
        endpoint = delivery_attempt.webhook_endpoint
        deliveries = WebhookDeliveryAttempt.objects.filter(
            webhook_event=delivery_attempt.webhook_event, webhook_endpoint=endpoint,
        )
        if deliveries.filter(is_success=True).exists():
            raise WalletError("This event was already delivered to the endpoint")
        if deliveries.count() >= endpoint.retry_count:
            raise WalletError("Maximum retry attempts exceeded")
        return self.forward_webhook_to_endpoint(delivery_attempt.webhook_event, endpoint)

    def retry_all_failed_deliveries(self, limit=None):
        """Retry every event/endpoint pair whose deliveries all failed and that has attempts left."""
        retried = 0
        seen = set()
        window_start = timezone.now() - timedelta(hours=int(wallet_settings.WEBHOOK_RETRY_WINDOW_HOURS))
        failed = WebhookDeliveryAttempt.objects.filter(is_success=False, created_at__gte=window_start).select_related(
            'webhook_event', 'webhook_endpoint',
        ).order_by('-created_at')
        for attempt in failed:
            pair = (attempt.webhook_event_id, attempt.webhook_endpoint_id)
            if pair in seen:
                continue
            seen.add(pair)
            deliveries = WebhookDeliveryAttempt.objects.filter(
                webhook_event_id=pair[0], webhook_endpoint_id=pair[1],
            )
            if deliveries.filter(is_success=True).exists():
                continue
            if deliveries.count() >= attempt.webhook_endpoint.retry_count or not attempt.webhook_endpoint.is_active:
                continue
            self.forward_webhook_to_endpoint(attempt.webhook_event, attempt.webhook_endpoint)
            retried += 1
            if limit and retried >= limit:
                break
        return retried

    # ------------------------------------------------------------------
    # Endpoint management
    # ------------------------------------------------------------------

    def register_webhook_endpoint(self, name, url, wallets=None, headers=None, retry_count=3, timeout=10,
                                  secret='', event_types=None):
        endpoint = WebhookEndpoint.objects.create(
            name=name, url=url, headers=headers or {}, retry_count=retry_count, timeout=timeout,
            secret=secret or '', event_types=list(event_types or []),
        )
        if wallets:
            endpoint.wallets.set(wallets)
        return endpoint

    @staticmethod
    def prune(retention_days=None):
        """
        Delete old operational data so tables stay small: processed webhook events
        (and their deliveries) and delivery attempts older than
        ``WALLET_WEBHOOK_RETENTION_DAYS``, plus expired idempotency records.
        Unprocessed events and all ledger data are always kept.
        """
        from wallet.models import IdempotencyRecord

        result = {'webhook_events': 0, 'delivery_attempts': 0, 'idempotency_records': 0}
        days = retention_days if retention_days is not None else wallet_settings.WEBHOOK_RETENTION_DAYS
        if days is not None:
            cutoff = timezone.now() - timedelta(days=int(days))
            result['delivery_attempts'] = WebhookDeliveryAttempt.objects.filter(created_at__lt=cutoff).delete()[0]
            result['webhook_events'] = WebhookEvent.objects.filter(
                processed=True, created_at__lt=cutoff,
            ).delete()[1].get('wallet.WebhookEvent', 0)
        expired = timezone.now() - timedelta(hours=int(wallet_settings.IDEMPOTENCY_TTL_HOURS))
        result['idempotency_records'] = IdempotencyRecord.objects.filter(created_at__lt=expired).delete()[0]
        return result

    def get_webhook_event(self, event_id):
        return WebhookEvent.objects.filter(pk=event_id).first()

    def list_webhook_events(self, event_type=None, processed=None, limit=100):
        queryset = WebhookEvent.objects.all()
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        if processed is not None:
            queryset = queryset.filter(processed=processed)
        return list(queryset.order_by('-created_at')[:limit])
