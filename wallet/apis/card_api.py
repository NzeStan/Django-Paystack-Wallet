from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404

from wallet.models import Card, Wallet
from wallet.serializers.card_serializer import (
    CardSerializer, CardDetailSerializer, CardUpdateSerializer,
    CardChargeSerializer, CardInitializeSerializer
)
from wallet.services.wallet_service import WalletService


class IsCardOwner(permissions.BasePermission):
    """Permission to check if user is the card owner"""
    
    def has_object_permission(self, request, view, obj):
        return obj.wallet.user == request.user


class CardViewSet(viewsets.ModelViewSet):
    """
    API endpoint for cards
    """
    serializer_class = CardSerializer
    permission_classes = [permissions.IsAuthenticated, IsCardOwner]
    http_method_names = ['get', 'put', 'patch', 'delete', 'post', 'head', 'options']  # No POST - cards are added via payment flow
    
    def get_queryset(self):
        """Get cards for the current user's wallets"""
        user_wallets = Wallet.objects.filter(user=self.request.user)
        return Card.objects.filter(wallet__in=user_wallets)
    
    def get_serializer_class(self):
        """Return the appropriate serializer based on action"""
        if self.action == 'retrieve':
            return CardDetailSerializer
        elif self.action in ['update', 'partial_update']:
            return CardUpdateSerializer
        elif self.action == 'charge':
            return CardChargeSerializer
        elif self.action == 'initialize':
            return CardInitializeSerializer
        
        return self.serializer_class
    
    def destroy(self, request, *args, **kwargs):
        """Remove a card"""
        card = self.get_object()
        
        # Instead of deletion, mark as inactive
        card.remove()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['post'])
    def charge(self, request, pk=None):
        """
        Charge a saved card
        """
        card = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        
        try:
            # Check if card is active
            if not card.is_active:
                return Response(
                    {"detail": _("Card is inactive")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if card is expired
            if card.is_expired:
                return Response(
                    {"detail": _("Card is expired")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Add request data to metadata
            metadata = serializer.validated_data.get('metadata', {})
            metadata.update({
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT')
            })
            
            # Charge card
            charge_data = wallet_service.charge_saved_card(
                card=card,
                amount=serializer.validated_data['amount'],
                reference=serializer.validated_data.get('reference'),
                metadata=metadata
            )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def initialize(self, request):
        """
        Initialize a card payment
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        
        try:
            # Get wallet
            wallet_id = request.query_params.get('wallet_id')
            if wallet_id:
                wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
            else:
                # Get or create default wallet
                wallet = Wallet.objects.filter(user=request.user).first()
                if not wallet:
                    wallet = wallet_service.get_wallet(request.user)
            
            # Add request data to metadata
            metadata = serializer.validated_data.get('metadata', {})
            metadata.update({
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT')
            })
            
            # Initialize Paystack transaction
            charge_data = wallet_service.initialize_card_charge(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                email=serializer.validated_data.get('email', request.user.email),
                reference=serializer.validated_data.get('reference'),
                callback_url=serializer.validated_data.get('callback_url'),
                metadata=metadata
            )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """
        Set card as default
        """
        card = self.get_object()
        
        try:
            card.set_as_default()
            return Response(
                {"detail": _("Card set as default successfully")},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": _("Direct card creation is not allowed.")},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )     # i aded this create method because i added post in http_method_names