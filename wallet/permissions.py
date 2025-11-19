"""
Permissions for Django Paystack Wallet

This module provides custom permissions for the wallet API.
"""

from rest_framework import permissions


class IsWebhookEndpointOwner(permissions.BasePermission):
    """
    Permission class to ensure only webhook endpoint owners can modify their endpoints.
    """
    
    def has_object_permission(self, request, view, obj):
        """
        Check if the user has permission to access the webhook endpoint.
        
        Args:
            request: The request object
            view: The view object
            obj: The webhook endpoint object
            
        Returns:
            True if the user has permission, False otherwise
        """
        # Staff users can access all endpoints
        if request.user.is_staff:
            return True
        
        # Check if the endpoint is associated with any of the user's wallets
        user_wallets = request.user.wallets.all()
        return obj.wallets.filter(id__in=user_wallets).exists()