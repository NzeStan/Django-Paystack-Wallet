from django.db import models
from django.utils.translation import gettext_lazy as _

from wallet.models.base import BaseModel


class WebhookEvent(BaseModel):
    """A webhook received from Paystack. Stored before processing so it can be replayed."""

    event_type = models.CharField(max_length=100, db_index=True, verbose_name=_('Event type'))
    payload = models.JSONField(verbose_name=_('Payload'))
    reference = models.CharField(max_length=150, blank=True, null=True, db_index=True, verbose_name=_('Reference'))
    idempotency_key = models.CharField(
        max_length=64, unique=True, verbose_name=_('Idempotency key'),
        help_text=_('SHA-256 of the raw body; Paystack retries of the same event share it'),
    )
    signature = models.CharField(max_length=255, blank=True, default='', verbose_name=_('Signature'))
    is_valid = models.BooleanField(default=True, verbose_name=_('Is valid'))
    processed = models.BooleanField(default=False, db_index=True, verbose_name=_('Processed'))
    processed_at = models.DateTimeField(blank=True, null=True, verbose_name=_('Processed at'))
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    processing_error = models.TextField(blank=True, default='', verbose_name=_('Processing error'))
    transaction = models.ForeignKey(
        'wallet.Transaction', on_delete=models.SET_NULL, related_name='webhook_events', blank=True, null=True,
        verbose_name=_('Transaction'),
    )

    class Meta:
        verbose_name = _('Webhook event')
        verbose_name_plural = _('Webhook events')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} - {self.reference or '-'}"

    @property
    def data(self):
        return (self.payload or {}).get('data') or {}


class WebhookEndpoint(BaseModel):
    """
    An HTTP endpoint that receives a copy of processed Paystack events
    (enable with ``WALLET_ENABLE_WEBHOOK_FORWARDING``). Useful when another
    service needs the events; in-process code should use signals instead.

    Deliveries are signed: ``X-Wallet-Signature`` is the HMAC-SHA512 of the
    body using ``secret``.
    """

    name = models.CharField(max_length=255, verbose_name=_('Name'))
    url = models.URLField(max_length=500, verbose_name=_('URL'))
    secret = models.CharField(max_length=255, blank=True, default='', verbose_name=_('Signing secret'))
    event_types = models.JSONField(
        default=list, blank=True, verbose_name=_('Event types'), help_text=_('Empty = all events'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('Is active'))
    wallets = models.ManyToManyField(
        'wallet.Wallet', related_name='webhook_endpoints', blank=True, verbose_name=_('Wallets'),
        help_text=_('Only forward events for these wallets; empty = all'),
    )
    headers = models.JSONField(default=dict, blank=True, verbose_name=_('Extra headers'))
    retry_count = models.PositiveSmallIntegerField(default=3, verbose_name=_('Max attempts'))
    timeout = models.PositiveSmallIntegerField(default=10, verbose_name=_('Timeout (seconds)'))

    class Meta:
        verbose_name = _('Webhook endpoint')
        verbose_name_plural = _('Webhook endpoints')
        ordering = ['name']

    def __str__(self):
        return self.name

    def accepts(self, event_type):
        return not self.event_types or event_type in self.event_types


class WebhookDeliveryAttempt(BaseModel):
    webhook_event = models.ForeignKey(
        WebhookEvent, on_delete=models.CASCADE, related_name='delivery_attempts', verbose_name=_('Webhook event'),
    )
    webhook_endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name='delivery_attempts', verbose_name=_('Endpoint'),
    )
    request_data = models.JSONField(default=dict, blank=True, verbose_name=_('Request data'))
    response_code = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name=_('Response code'))
    response_body = models.TextField(blank=True, default='', verbose_name=_('Response body'))
    is_success = models.BooleanField(default=False, db_index=True, verbose_name=_('Is success'))
    attempt_number = models.PositiveSmallIntegerField(default=1, verbose_name=_('Attempt number'))

    class Meta:
        verbose_name = _('Webhook delivery attempt')
        verbose_name_plural = _('Webhook delivery attempts')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.webhook_endpoint.name} - {self.webhook_event.event_type} - #{self.attempt_number}"
