"""Reusable DRF permissions."""
from rest_framework import permissions


class IsWalletOwner(permissions.BasePermission):
    """Object belongs to the requesting user's wallet (works for Wallet and anything with ``.wallet``)."""

    def has_object_permission(self, request, view, obj):
        wallet = obj if hasattr(obj, 'user_id') and not hasattr(obj, 'wallet_id') else getattr(obj, 'wallet', None)
        return bool(wallet is not None and wallet.user_id == request.user.pk)


class HasOperationalWallet(permissions.BasePermission):
    """The user has a wallet that is active and not locked."""

    message = 'Your wallet is locked or inactive'

    def has_permission(self, request, view):
        wallet = getattr(request.user, 'wallet', None) if request.user.is_authenticated else None
        return bool(wallet is not None and wallet.is_operational)


class IsWebhookEndpointOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        return obj.wallets.filter(user=request.user).exists()
