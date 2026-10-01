from rest_framework import serializers

from wallet.models import WebhookDeliveryAttempt, WebhookEndpoint, WebhookEvent


class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = [
            'id', 'event_type', 'reference', 'payload', 'processed', 'processed_at', 'processing_attempts',
            'processing_error', 'transaction', 'created_at',
        ]
        read_only_fields = fields


class WebhookEndpointSerializer(serializers.ModelSerializer):
    secret = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = WebhookEndpoint
        fields = [
            'id', 'name', 'url', 'secret', 'event_types', 'is_active', 'wallets', 'headers', 'retry_count',
            'timeout', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class WebhookDeliveryAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDeliveryAttempt
        fields = [
            'id', 'webhook_event', 'webhook_endpoint', 'attempt_number', 'request_data', 'response_code',
            'response_body', 'is_success', 'created_at',
        ]
        read_only_fields = fields
