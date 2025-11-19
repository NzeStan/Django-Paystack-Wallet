"""
Webhook Serializers for Django Paystack Wallet

This module provides serializers for webhook-related models.
"""

from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from wallet.models import WebhookEvent, WebhookEndpoint, WebhookDeliveryAttempt


class WebhookEventSerializer(serializers.ModelSerializer):
    """Serializer for webhook events"""
    
    event_type_display = serializers.CharField(
        source='get_event_type_display',
        read_only=True
    )
    delivery_attempts_count = serializers.IntegerField(
        source='delivery_attempts.count',
        read_only=True
    )
    
    class Meta:
        model = WebhookEvent
        fields = [
            'id',
            'event_type',
            'event_type_display',
            'payload',
            'reference',
            'processed',
            'processed_at',
            'signature',
            'is_valid',
            'transaction',
            'delivery_attempts_count',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'processed',
            'processed_at',
            'created_at',
            'updated_at'
        ]


class WebhookEventDetailSerializer(WebhookEventSerializer):
    """Detailed serializer for webhook events with delivery attempts"""
    
    delivery_attempts = serializers.SerializerMethodField()
    
    class Meta(WebhookEventSerializer.Meta):
        fields = WebhookEventSerializer.Meta.fields + ['delivery_attempts']
    
    def get_delivery_attempts(self, obj):
        """Get delivery attempts for this event"""
        attempts = obj.delivery_attempts.all()[:10]  # Limit to last 10
        return WebhookDeliveryAttemptSerializer(attempts, many=True).data


class WebhookEndpointSerializer(serializers.ModelSerializer):
    """Serializer for webhook endpoints"""
    
    wallets_count = serializers.IntegerField(
        source='wallets.count',
        read_only=True
    )
    total_deliveries = serializers.IntegerField(
        source='delivery_attempts.count',
        read_only=True
    )
    successful_deliveries = serializers.SerializerMethodField()
    failed_deliveries = serializers.SerializerMethodField()
    
    class Meta:
        model = WebhookEndpoint
        fields = [
            'id',
            'name',
            'url',
            'secret',
            'event_types',
            'is_active',
            'wallets',
            'wallets_count',
            'headers',
            'retry_count',
            'timeout',
            'total_deliveries',
            'successful_deliveries',
            'failed_deliveries',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'created_at',
            'updated_at'
        ]
        extra_kwargs = {
            'secret': {'write_only': True},
            'wallets': {'required': False}
        }
    
    def get_successful_deliveries(self, obj):
        """Get count of successful deliveries"""
        return obj.delivery_attempts.filter(is_success=True).count()
    
    def get_failed_deliveries(self, obj):
        """Get count of failed deliveries"""
        return obj.delivery_attempts.filter(is_success=False).count()
    
    def validate_url(self, value):
        """Validate URL is accessible"""
        if not value.startswith(('http://', 'https://')):
            raise serializers.ValidationError(
                _("URL must start with http:// or https://")
            )
        return value
    
    def validate_retry_count(self, value):
        """Validate retry count is reasonable"""
        if value < 0:
            raise serializers.ValidationError(
                _("Retry count cannot be negative")
            )
        if value > 10:
            raise serializers.ValidationError(
                _("Retry count cannot exceed 10")
            )
        return value
    
    def validate_timeout(self, value):
        """Validate timeout is reasonable"""
        if value and value < 1:
            raise serializers.ValidationError(
                _("Timeout must be at least 1 second")
            )
        if value and value > 120:
            raise serializers.ValidationError(
                _("Timeout cannot exceed 120 seconds")
            )
        return value


class WebhookEndpointDetailSerializer(WebhookEndpointSerializer):
    """Detailed serializer for webhook endpoints with recent attempts"""
    
    recent_attempts = serializers.SerializerMethodField()
    
    class Meta(WebhookEndpointSerializer.Meta):
        fields = WebhookEndpointSerializer.Meta.fields + ['recent_attempts']
    
    def get_recent_attempts(self, obj):
        """Get recent delivery attempts for this endpoint"""
        attempts = obj.delivery_attempts.all()[:20]  # Last 20 attempts
        return WebhookDeliveryAttemptSerializer(attempts, many=True).data


class WebhookDeliveryAttemptSerializer(serializers.ModelSerializer):
    """Serializer for webhook delivery attempts"""
    
    webhook_event_type = serializers.CharField(
        source='webhook_event.event_type',
        read_only=True
    )
    webhook_event_reference = serializers.CharField(
        source='webhook_event.reference',
        read_only=True
    )
    webhook_endpoint_name = serializers.CharField(
        source='webhook_endpoint.name',
        read_only=True
    )
    webhook_endpoint_url = serializers.CharField(
        source='webhook_endpoint.url',
        read_only=True
    )
    
    class Meta:
        model = WebhookDeliveryAttempt
        fields = [
            'id',
            'webhook_event',
            'webhook_event_type',
            'webhook_event_reference',
            'webhook_endpoint',
            'webhook_endpoint_name',
            'webhook_endpoint_url',
            'request_data',
            'response_code',
            'response_body',
            'is_success',
            'attempt_number',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'created_at',
            'updated_at'
        ]


class WebhookDeliveryAttemptDetailSerializer(WebhookDeliveryAttemptSerializer):
    """Detailed serializer for webhook delivery attempts"""
    
    webhook_event_data = WebhookEventSerializer(
        source='webhook_event',
        read_only=True
    )
    webhook_endpoint_data = WebhookEndpointSerializer(
        source='webhook_endpoint',
        read_only=True
    )
    
    class Meta(WebhookDeliveryAttemptSerializer.Meta):
        fields = WebhookDeliveryAttemptSerializer.Meta.fields + [
            'webhook_event_data',
            'webhook_endpoint_data'
        ]