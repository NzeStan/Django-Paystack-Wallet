"""
Django Paystack Wallet - Card API
Comprehensive REST API for card management
PROPERLY ARCHITECTED: Following project patterns with wallet.user references and proper relationships
"""
import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.db.models import Count, Sum, Avg, Q
from django.db import transaction as db_transaction
from decimal import Decimal

from wallet.models import Card, Wallet, Transaction
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
from wallet.services.transaction_service import TransactionService
from wallet.exceptions import WalletError
from wallet.constants import (
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_FAILED
)
from wallet.utils import generate_transaction_reference


# Configure logging
logger = logging.getLogger(__name__)


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_client_ip(request):
    """
    Extract client IP from request
    
    Args:
        request: HTTP request
        
    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Get first IP from list (client IP)
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


# ==========================================
# PERMISSIONS
# ==========================================

class IsCardOwner(permissions.BasePermission):
    """
    Permission to check if user is the card owner
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if request user owns the card through wallet"""
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
        Get detailed information about a specific card including transaction statistics
    
    update:
        RESTRICTED - Update not allowed, use specific actions
    
    partial_update:
        RESTRICTED - Partial update not allowed, use specific actions
    
    destroy:
        Remove a card (soft delete - marks as inactive)
    
    charge:
        Charge a saved card for a transaction (creates PENDING transaction first)
    
    initialize:
        Initialize a new card payment (returns authorization URL)
    
    set_default:
        Set a card as the default for its wallet
    
    statistics:
        Get comprehensive statistics for a card using card.transactions
    
    activate:
        Activate an inactive card
    
    deactivate:
        Deactivate a card
    """
    
    serializer_class = CardSerializer
    permission_classes = [permissions.IsAuthenticated, IsCardOwner]
    http_method_names = ['get', 'delete', 'post', 'head', 'options']  # No PUT/PATCH
    
    def __init__(self, **kwargs):
        """Initialize with wallet and transaction services"""
        super().__init__(**kwargs)
        self.wallet_service = WalletService()
        self.transaction_service = TransactionService()
    
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
            {
                "detail": _("Direct card creation is not allowed. Use the initialize action to add a card through payment."),
                "hint": _("POST to /api/cards/initialize/ to start the card payment flow")
            },
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
            
            logger.info(
                f"Card {card.id} marked as inactive by user {card.wallet.user.id}"
            )
            
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
    @db_transaction.atomic
    def charge(self, request, pk=None):
        """
        Charge a saved card
        
        CRITICAL: This creates a PENDING transaction FIRST before calling Paystack,
        ensuring the transaction exists when the webhook arrives.
        
        Card IS directly linked to Transaction (card.transactions.all()), so we properly
        link the transaction to the card.
        
        Args:
            request: HTTP request with amount and optional metadata
            pk: Card ID
            
        Returns:
            Response: Charge response data with transaction details
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
            
            # Generate reference
            reference = serializer.validated_data.get('reference') or generate_transaction_reference()
            amount = serializer.validated_data['amount']
            
            # Convert amount to kobo (Paystack uses kobo/cents)
            amount_in_kobo = int(Decimal(amount) * 100)
            
            # Prepare metadata following project pattern
            metadata = serializer.validated_data.get('metadata', {})
            if isinstance(metadata, dict):
                metadata = metadata.copy()
            else:
                metadata = {}
            
            metadata.update({
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'wallet_id': str(card.wallet.id),
                'user_id': str(card.wallet.user.id),  # Reference through wallet.user
                'card_id': str(card.id)
            })
            
            logger.info(
                f"Initiating card charge for card {card.id}: "
                f"amount={amount}, reference={reference}"
            )
            
            # CRITICAL: Create PENDING transaction FIRST
            # This ensures the transaction exists when the webhook arrives
            transaction = Transaction.objects.create(
                wallet=card.wallet,
                amount=amount,
                transaction_type=TRANSACTION_TYPE_DEPOSIT,
                status=TRANSACTION_STATUS_PENDING,
                description=serializer.validated_data.get('description', f"Card charge of {amount}"),
                metadata=metadata,
                reference=reference,
                payment_method='card',
                card=card  # Card IS directly linked to Transaction
            )
            
            logger.info(
                f"Created PENDING transaction {transaction.id} for card charge: "
                f"card={card.id}, reference={reference}, amount={amount}"
            )
            
            try:
                # Get email from card or wallet.user (NOT request.user)
                email = card.email or card.wallet.user.email
                
                # Now charge the card via Paystack
                charge_data = self.wallet_service.paystack.charge_authorization(
                    amount=amount_in_kobo,
                    email=email,
                    authorization_code=card.paystack_authorization_code,
                    reference=reference,
                    metadata=metadata
                )
                
                logger.info(
                    f"Card {card.id} charged via Paystack: reference={reference}, "
                    f"status={charge_data.get('status')}"
                )
                
                # Return charge data with transaction info
                return Response(
                    {
                        **charge_data,
                        "transaction": {
                            "id": str(transaction.id),
                            "reference": transaction.reference,
                            "status": transaction.status,
                            "amount": float(transaction.amount.amount),
                            "currency": str(transaction.amount.currency)
                        }
                    },
                    status=status.HTTP_200_OK
                )
            
            except Exception as paystack_error:
                # If Paystack call fails, mark transaction as failed
                transaction.status = TRANSACTION_STATUS_FAILED
                transaction.failed_reason = f"Paystack charge failed: {str(paystack_error)}"
                transaction.save(update_fields=['status', 'failed_reason', 'updated_at'])
                
                logger.error(
                    f"Paystack charge failed for transaction {transaction.id}: {str(paystack_error)}",
                    exc_info=True
                )
                
                # Re-raise the error
                raise
        
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
        After successful payment, the card is automatically saved by webhook.
        
        SECURITY: Card holder name and email are auto-filled from wallet.user
        and cannot be overridden by the customer.
        
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
            wallet = get_object_or_404(
                Wallet.objects.select_related('user'),
                id=wallet_id,
                user=request.user
            )
        else:
            # Get or create default wallet
            wallet = self.wallet_service.get_wallet(request.user)
        
        try:
            # SECURITY: Email always from wallet.user (NOT from request data)
            email = wallet.user.email
            
            if not email:
                return Response(
                    {"detail": _("User email is required for card payment")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Prepare metadata following project pattern
            metadata = serializer.validated_data.get('metadata', {})
            if isinstance(metadata, dict):
                metadata = metadata.copy()
            else:
                metadata = {}
            
            metadata.update({
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                # SECURITY: Card holder name auto-filled from wallet.user
                'cardholder_name': wallet.user.get_full_name() or wallet.user.email
            })
            
            logger.info(
                f"Initializing card payment for wallet {wallet.id}: "
                f"amount={serializer.validated_data['amount']}, "
                f"user={wallet.user.id}, cardholder={metadata['cardholder_name']}"
            )
            
            # Initialize Paystack transaction (this already creates PENDING transaction)
            charge_data = self.wallet_service.initialize_card_charge(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                email=email,  # Use wallet.user.email
                reference=serializer.validated_data.get('reference'),
                callback_url=serializer.validated_data.get('callback_url'),
                metadata=metadata
            )
            
            logger.info(
                f"Card payment initialized for wallet {wallet.id}: "
                f"reference={charge_data.get('reference')}"
            )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(
                f"Error initializing card payment for wallet {wallet.id}: {str(e)}",
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
            
            logger.info(
                f"Card {card.id} set as default for wallet {card.wallet.id} "
                f"by user {card.wallet.user.id}"
            )
            
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
        
        Card IS directly linked to Transaction through card.transactions,
        so we can properly query card.transactions.aggregate()
        
        Args:
            request: HTTP request
            pk: Card ID
            
        Returns:
            Response: Card statistics
        """
        card = self.get_object()
        
        try:
            # Gather statistics using card.transactions (proper relationship)
            transactions = card.transactions.aggregate(
                total=Count('id'),
                successful=Count('id', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
                failed=Count('id', filter=~Q(status=TRANSACTION_STATUS_SUCCESS)),
                total_amount=Sum('amount', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
                average_amount=Avg('amount', filter=Q(status=TRANSACTION_STATUS_SUCCESS))
            )
            
            # Get last transaction
            last_transaction = card.transactions.order_by('-created_at').first()
            
            # Build statistics response
            statistics = {
                'id': card.id,
                'card_type': card.card_type,
                'last_four': card.last_four,
                'masked_pan': card.masked_pan,
                'total_transactions': transactions['total'] or 0,
                'successful_transactions': transactions['successful'] or 0,
                'failed_transactions': transactions['failed'] or 0,
                'total_amount': float(transactions['total_amount']) if transactions['total_amount'] is not None else 0,
                'average_amount': float(transactions['average_amount']) if transactions['average_amount'] is not None else 0,
                'is_default': card.is_default,
                'is_active': card.is_active,
                'is_expired': card.is_expired,
                'is_valid': card.is_valid,
                'last_used': last_transaction.created_at if last_transaction else None,
                'created_at': card.created_at,
            }
            
            logger.info(
                f"Retrieved statistics for card {card.id}: "
                f"{statistics['total_transactions']} transactions"
            )
            
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
        Activate an inactive card
        
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
            
            logger.info(
                f"Card {card.id} activated by user {card.wallet.user.id}"
            )
            
            return Response(
                {
                    "detail": _("Card activated successfully"),
                    "card": CardSerializer(card).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(
                f"Error activating card: {str(e)}",
                exc_info=True
            )
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
            
            logger.info(
                f"Card {card.id} deactivated by user {card.wallet.user.id}"
            )
            
            return Response(
                {
                    "detail": _("Card deactivated successfully"),
                    "card": CardSerializer(card).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(
                f"Error deactivating card: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )