"""
Django Paystack Wallet - Card API
Comprehensive REST API for card management
"""
import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.db.models import Count, Sum, Avg, Q
from django.db import transaction as db_transaction

from wallet.models import Card, Wallet
from wallet.serializers.card_serializer import (
    CardSerializer,
    CardListSerializer,
    CardDetailSerializer,
    CardUpdateSerializer,
    CardChargeSerializer,
    CardInitializeSerializer,
    CardSetDefaultSerializer,
    CardStatisticsSerializer
)
from wallet.services.wallet_service import WalletService
from wallet.exceptions import WalletError
from wallet.constants import TRANSACTION_STATUS_SUCCESS


# Configure logging
logger = logging.getLogger(__name__)


# ==========================================
# PERMISSIONS
# ==========================================

class IsCardOwner(permissions.BasePermission):
    """
    Permission to check if user is the card owner
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if request user owns the card"""
        return obj.wallet.user == request.user


# ==========================================
# CARD VIEWSET
# ==========================================

class CardViewSet(viewsets.ModelViewSet):
    """
    API endpoint for card management
    
    Provides operations for managing saved payment cards.
    Cards are added through payment flows and can be managed here.
    
    list:
        List all cards for the authenticated user's wallets
        with optional filtering by wallet, card type, status, etc.
    
    retrieve:
        Get detailed information about a specific card
    
    update:
        Update card information (name, email, default status)
    
    partial_update:
        Partially update card information
    
    destroy:
        Remove a card (soft delete - marks as inactive)
    
    charge:
        Charge a saved card for a transaction
    
    initialize:
        Initialize a new card payment (returns authorization URL)
    
    set_default:
        Set a card as the default for its wallet
    
    statistics:
        Get comprehensive statistics for a card
    
    activate:
        Activate an inactive card
    
    deactivate:
        Deactivate a card
    """
    
    serializer_class = CardSerializer
    permission_classes = [permissions.IsAuthenticated, IsCardOwner]
    http_method_names = ['get', 'put', 'patch', 'delete', 'post', 'head', 'options']
    
    def __init__(self, **kwargs):
        """Initialize with wallet service"""
        super().__init__(**kwargs)
        self.wallet_service = WalletService()
    
    def get_queryset(self):
        """
        Get cards for the current user's wallets with optimized queries
        
        Returns:
            QuerySet: Filtered and optimized card queryset
        """
        user = self.request.user
        
        # Get user's wallets
        user_wallets = Wallet.objects.filter(user=user)
        
        # Base queryset with optimized relations
        queryset = Card.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user'
        ).order_by('-is_default', '-created_at')
        
        # Apply filters from query parameters
        wallet_id = self.request.query_params.get('wallet_id')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)
        
        card_type = self.request.query_params.get('card_type')
        if card_type:
            queryset = queryset.by_card_type(card_type)
        
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        is_default = self.request.query_params.get('is_default')
        if is_default is not None:
            queryset = queryset.filter(is_default=is_default.lower() == 'true')
        
        is_expired = self.request.query_params.get('is_expired')
        if is_expired is not None:
            if is_expired.lower() == 'true':
                queryset = queryset.expired()
            else:
                queryset = queryset.not_expired()
        
        last_four = self.request.query_params.get('last_four')
        if last_four:
            queryset = queryset.by_last_four(last_four)
        
        # Search functionality
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.search(search)
        
        logger.debug(
            f"Card queryset for user {user.id}: {queryset.count()} cards"
        )
        
        return queryset
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action
        
        Returns:
            Serializer class
        """
        if self.action == 'list':
            return CardListSerializer
        elif self.action == 'retrieve':
            return CardDetailSerializer
        elif self.action in ['update', 'partial_update']:
            return CardUpdateSerializer
        elif self.action == 'charge':
            return CardChargeSerializer
        elif self.action == 'initialize':
            return CardInitializeSerializer
        elif self.action == 'set_default':
            return CardSetDefaultSerializer
        elif self.action == 'statistics':
            return CardStatisticsSerializer
        
        return self.serializer_class
    
    def create(self, request, *args, **kwargs):
        """
        Direct card creation is not allowed
        
        Cards are added through payment flows (initialize action).
        
        Args:
            request: HTTP request
            
        Returns:
            Response: Method not allowed
        """
        return Response(
            {"detail": _("Direct card creation is not allowed. Use the initialize action to add a card through payment.")},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )
    
    @db_transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """
        Remove a card (soft delete)
        
        Args:
            request: HTTP request
            
        Returns:
            Response: No content
        """
        card = self.get_object()
        
        try:
            # Soft delete
            card.remove()
            
            logger.info(f"Card {card.id} marked as inactive")
            
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except Exception as e:
            logger.error(
                f"Error removing card {card.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": _("An error occurred while removing the card")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def charge(self, request, pk=None):
        """
        Charge a saved card
        
        This action charges a saved card using its authorization code.
        The transaction is created and processed immediately.
        
        Args:
            request: HTTP request with amount and optional metadata
            pk: Card ID
            
        Returns:
            Response: Charge response data
        """
        card = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
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
            
            # Charge the card via wallet service
            charge_data = self.wallet_service.charge_saved_card(
                card=card,
                amount=serializer.validated_data['amount'],
                reference=serializer.validated_data.get('reference'),
                metadata=metadata
            )
            
            logger.info(
                f"Card {card.id} charged: amount={serializer.validated_data['amount']}"
            )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(
                f"Error charging card {card.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def initialize(self, request):
        """
        Initialize a card payment
        
        This action initializes a card charge with Paystack and returns
        an authorization URL where the user can complete the payment.
        After successful payment, the card is automatically saved.
        
        Args:
            request: HTTP request with payment details
            
        Returns:
            Response: Payment initialization data with authorization URL
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get wallet
        wallet_id = request.query_params.get('wallet_id')
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            # Get or create default wallet
            wallet = self.wallet_service.get_wallet(request.user)
        
        try:
            # Add request data to metadata
            metadata = serializer.validated_data.get('metadata', {})
            metadata.update({
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT')
            })
            
            # Initialize Paystack transaction
            charge_data = self.wallet_service.initialize_card_charge(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                email=serializer.validated_data.get('email', request.user.email),
                reference=serializer.validated_data.get('reference'),
                callback_url=serializer.validated_data.get('callback_url'),
                metadata=metadata
            )
            
            logger.info(
                f"Card payment initialized for wallet {wallet.id}: "
                f"amount={serializer.validated_data['amount']}"
            )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(
                f"Error initializing card payment: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def set_default(self, request, pk=None):
        """
        Set card as default for its wallet
        
        Args:
            request: HTTP request
            pk: Card ID
            
        Returns:
            Response: Success message
        """
        card = self.get_object()
        
        try:
            # Check if card is valid
            if not card.is_active:
                return Response(
                    {"detail": _("Cannot set an inactive card as default")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if card.is_expired:
                return Response(
                    {"detail": _("Cannot set an expired card as default")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            card.set_as_default()
            
            logger.info(f"Card {card.id} set as default")
            
            return Response(
                {
                    "detail": _("Card set as default successfully"),
                    "card": CardSerializer(card).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(
                f"Error setting card as default: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Get comprehensive statistics for a card
        
        Args:
            request: HTTP request
            pk: Card ID
            
        Returns:
            Response: Card statistics
        """
        card = self.get_object()
        
        try:
            # Gather statistics
            transactions = card.transactions.aggregate(
                total=Count('id'),
                successful=Count('id', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
                failed=Count('id', filter=~Q(status=TRANSACTION_STATUS_SUCCESS)),
                total_amount=Sum('amount', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
                average_amount=Avg('amount', filter=Q(status=TRANSACTION_STATUS_SUCCESS))
            )
            
            last_transaction = card.transactions.order_by('-created_at').first()
            
            statistics = {
                'id': card.id,
                'card_type': card.card_type,
                'last_four': card.last_four,
                'masked_pan': card.masked_pan,
                'total_transactions': transactions['total'],
                'successful_transactions': transactions['successful'],
                'failed_transactions': transactions['failed'],
                'total_amount': float(transactions['total_amount'].amount) if transactions['total_amount'] else 0,
                'average_amount': float(transactions['average_amount'].amount) if transactions['average_amount'] else 0,
                'is_default': card.is_default,
                'is_active': card.is_active,
                'is_expired': card.is_expired,
                'is_valid': card.is_valid,
                'last_used': last_transaction.created_at if last_transaction else None,
                'created_at': card.created_at,
            }
            
            return Response(statistics, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(
                f"Error getting card statistics: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": _("An error occurred while fetching statistics")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def activate(self, request, pk=None):
        """
        Activate a card
        
        Args:
            request: HTTP request
            pk: Card ID
            
        Returns:
            Response: Success message
        """
        card = self.get_object()
        
        try:
            # Check if card is expired
            if card.is_expired:
                return Response(
                    {"detail": _("Cannot activate an expired card")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            card.activate()
            
            logger.info(f"Card {card.id} activated")
            
            return Response(
                {
                    "detail": _("Card activated successfully"),
                    "card": CardSerializer(card).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(f"Error activating card: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def deactivate(self, request, pk=None):
        """
        Deactivate a card
        
        Args:
            request: HTTP request
            pk: Card ID
            
        Returns:
            Response: Success message
        """
        card = self.get_object()
        
        try:
            card.deactivate()
            
            logger.info(f"Card {card.id} deactivated")
            
            return Response(
                {
                    "detail": _("Card deactivated successfully"),
                    "card": CardSerializer(card).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(f"Error deactivating card: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )