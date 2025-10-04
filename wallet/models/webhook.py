from django.db import models
from django.utils.translation import gettext_lazy as _

from wallet.models.base import BaseModel
from wallet.constants import WEBHOOK_EVENTS


class WebhookEvent(BaseModel):
    """
    Webhook event model for storing webhook events received from Paystack
    """
    event_type = models.CharField(
        max_length=50,
        choices=WEBHOOK_EVENTS,
        verbose_name=_('Event type')
    )
    payload = models.JSONField(
        verbose_name=_('Payload')
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Reference')
    )
    processed = models.BooleanField(
        default=False,
        verbose_name=_('Processed')
    )
    processed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('Processed at')
    )
    signature = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('Signature')
    )
    is_valid = models.BooleanField(
        default=True,
        verbose_name=_('Is valid')
    )
    transaction = models.ForeignKey(
        'wallet.Transaction',
        on_delete=models.SET_NULL,
        related_name='webhook_events',
        blank=True,
        null=True,
        verbose_name=_('Transaction')
    )
    
    class Meta:
        verbose_name = _('Webhook event')
        verbose_name_plural = _('Webhook events')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['reference']),
            models.Index(fields=['processed']),
        ]
    
    def __str__(self):
        return f"{self.get_event_type_display()} - {self.reference} ({self.created_at})"


class WebhookEndpoint(BaseModel):
    """
    Webhook endpoint model for storing custom webhook endpoints for notifications
    """
    name = models.CharField(
        max_length=255,
        verbose_name=_('Name')
    )
    url = models.URLField(
        max_length=500,
        verbose_name=_('URL')
    )
    secret = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Secret')
    )
    event_types = models.JSONField(
        default=list,
        verbose_name=_('Event types'),
        help_text=_('List of event types to send to this endpoint')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active')
    )
    wallets = models.ManyToManyField(
        'wallet.Wallet',
        related_name='webhook_endpoints',
        blank=True,
        verbose_name=_('Wallets'),
        help_text=_('Specific wallets to send events for, leave empty for all wallets')
    )
    headers = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_('Headers'),
        help_text=_('Custom headers to send with the webhook')
    )
    retry_count = models.PositiveSmallIntegerField(
        default=3,
        verbose_name=_('Retry count'),
        help_text=_('Number of times to retry failed webhooks')
    )
    
    class Meta:
        verbose_name = _('Webhook endpoint')
        verbose_name_plural = _('Webhook endpoints')
        ordering = ['name']
    
    def __str__(self):
        return self.name


class WebhookDeliveryAttempt(BaseModel):
    """
    Webhook delivery attempt model for tracking webhook delivery attempts
    """
    webhook_event = models.ForeignKey(
        WebhookEvent,
        on_delete=models.CASCADE,
        related_name='delivery_attempts',
        verbose_name=_('Webhook event')
    )
    webhook_endpoint = models.ForeignKey(
        WebhookEndpoint,
        on_delete=models.CASCADE,
        related_name='delivery_attempts',
        verbose_name=_('Webhook endpoint')
    )
    request_data = models.JSONField(
        verbose_name=_('Request data')
    )
    response_code = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name=_('Response code')
    )
    response_body = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Response body')
    )
    is_success = models.BooleanField(
        default=False,
        verbose_name=_('Is success')
    )
    attempt_number = models.PositiveSmallIntegerField(
        default=1,
        verbose_name=_('Attempt number')
    )
    
    class Meta:
        verbose_name = _('Webhook delivery attempt')
        verbose_name_plural = _('Webhook delivery attempts')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.webhook_endpoint.name} - {self.webhook_event.event_type} - Attempt {self.attempt_number}"