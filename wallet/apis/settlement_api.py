"""
Django Paystack Wallet - Settlement API
Comprehensive API endpoints with query optimization and permissions
"""
import logging
from decimal import Decimal
from typing import Optional
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.db.models import Q
from djmoney.money import Money

from wallet.models import (
    Settlement,
    SettlementSchedule,
    BankAccount,
    Wallet
)
from wallet.serializers.settlement_serializer import (
    SettlementSerializer,
    SettlementDetailSerializer,
    SettlementListSerializer,
    SettlementCreateSerializer,
    SettlementUpdateSerializer,
    SettlementStatusSerializer,
    SettlementScheduleSerializer,
    SettlementScheduleCreateSerializer,
    SettlementScheduleUpdateSerializer,
    SettlementScheduleListSerializer
)
from wallet.services.settlement_service import SettlementService
from wallet.exceptions import (
    SettlementError,
    InsufficientFunds,
    WalletLocked
)


logger = logging.getLogger(__name__)


# ==========================================
# PERMISSIONS
# ==========================================


class IsSettlementOwner(permissions.BasePermission):
    """
    Permission to check if user is the settlement owner
    
    Allows access only if the settlement belongs to the user's wallet.
    """
    
    def has_object_permission(self, request, view, obj):
        """
        Check if user owns the settlement
        
        Args:
            request: HTTP request
            view: View being accessed
            obj: Settlement object
            
        Returns:
            bool: True if user owns the settlement
        """
        return obj.wallet.user == request.user


# ==========================================
# SETTLEMENT VIEWSET
# ==========================================


class SettlementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for settlements
    
    Provides read-only access to settlements with custom actions for
    creating, verifying, and retrying settlements.
    
    List/Retrieve: GET /api/settlements/
    Create: POST /api/settlements/create_settlement/
    Verify: GET /api/settlements/{id}/verify/
    Retry: POST /api/settlements/{id}/retry/
    """
    
    serializer_class = SettlementSerializer
    permission_classes = [permissions.IsAuthenticated, IsSettlementOwner]
    filterset_fields = ['status', 'bank_account']
    search_fields = ['reference', 'paystack_transfer_code', 'reason']
    ordering_fields = ['created_at', 'settled_at', 'amount']
    
    def get_queryset(self):
        """
        Get settlements for the current user's wallets with optimized queries
        
        Returns:
            QuerySet: Filtered and optimized settlement queryset
        """
        user = self.request.user
        
        # Get user's wallets
        user_wallets = Wallet.objects.filter(user=user)
        
        # Build optimized queryset
        queryset = Settlement.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank',
            'transaction'
        ).order_by('-created_at')
        
        # Apply additional filters from query parameters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        bank_account_filter = self.request.query_params.get('bank_account')
        if bank_account_filter:
            queryset = queryset.filter(bank_account_id=bank_account_filter)
        
        # Date range filters
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        logger.debug(
            f"Settlement queryset for user {user.id}: {queryset.count()} settlements"
        )
        
        return queryset
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action
        
        Returns:
            Serializer class: Appropriate serializer for the action
        """
        action_serializers = {
            'list': SettlementListSerializer,
            'retrieve': SettlementDetailSerializer,
            'create_settlement': SettlementCreateSerializer,
            'update': SettlementUpdateSerializer,
            'partial_update': SettlementUpdateSerializer,
        }
        
        return action_serializers.get(self.action, self.serializer_class)
    
    @action(detail=False, methods=['post'])
    def create_settlement(self, request):
        """
        Create a new settlement
        
        POST /api/settlements/create_settlement/?wallet_id=<wallet_id>
        
        Body:
        {
            "bank_account_id": "uuid",
            "amount": "100.00",
            "reason": "Settlement reason (optional)",
            "metadata": {} (optional)
        }
        
        Returns:
            201: Settlement created
            400: Bad request (validation errors)
        """
        logger.info(f"Creating settlement for user {request.user.id}")
        
        # Get wallet from query parameter
        wallet_id = request.query_params.get('wallet_id')
        
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            # Get default wallet
            wallet = Wallet.objects.filter(user=request.user).first()
            if not wallet:
                logger.warning(f"No wallet found for user {request.user.id}")
                return Response(
                    {"detail": _("No wallet found")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Validate request data
        serializer = self.get_serializer(data=request.data, wallet=wallet)
        serializer.is_valid(raise_exception=True)
        
        # Get validated data
        validated_data = serializer.validated_data
        
        # Get bank account
        bank_account = get_object_or_404(
            BankAccount,
            id=validated_data['bank_account_id'],
            wallet=wallet
        )
        
        # Create Money object for amount
        amount = Money(
            validated_data['amount'],
            wallet.balance.currency
        )
        
        # Initialize settlement service
        settlement_service = SettlementService()
        
        try:
            # Create settlement
            settlement = settlement_service.create_settlement(
                wallet=wallet,
                bank_account=bank_account,
                amount=amount,
                reason=validated_data.get('reason'),
                metadata=validated_data.get('metadata'),
                auto_process=True
            )
            
            logger.info(
                f"Settlement {settlement.id} created successfully for user {request.user.id}"
            )
            
            # Return created settlement
            return Response(
                SettlementDetailSerializer(settlement).data,
                status=status.HTTP_201_CREATED
            )
            
        except WalletLocked as e:
            logger.warning(f"Wallet locked: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except InsufficientFunds as e:
            logger.warning(f"Insufficient funds: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except SettlementError as e:
            logger.error(f"Settlement error: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected error creating settlement: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while creating the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def verify(self, request, pk=None):
        """
        Verify a settlement's status with Paystack
        
        GET /api/settlements/{id}/verify/
        
        Returns:
            200: Settlement status updated
            400: Bad request
            404: Settlement not found
        """
        settlement = self.get_object()
        
        logger.info(f"Verifying settlement {settlement.id}")
        
        # Initialize settlement service
        settlement_service = SettlementService()
        
        try:
            # Verify settlement
            updated_settlement = settlement_service.verify_settlement(settlement)
            
            logger.info(f"Settlement {settlement.id} verified: status={updated_settlement.status}")
            
            return Response(
                SettlementDetailSerializer(updated_settlement).data,
                status=status.HTTP_200_OK
            )
            
        except SettlementError as e:
            logger.error(f"Error verifying settlement: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected error verifying settlement: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while verifying the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retry a failed settlement
        
        POST /api/settlements/{id}/retry/
        
        Returns:
            200: Settlement retried
            400: Bad request (not failed or insufficient funds)
            404: Settlement not found
        """
        settlement = self.get_object()
        
        logger.info(f"Retrying settlement {settlement.id}")
        
        # Initialize settlement service
        settlement_service = SettlementService()
        
        try:
            # Retry settlement
            updated_settlement = settlement_service.retry_settlement(settlement)
            
            logger.info(f"Settlement {settlement.id} retried: status={updated_settlement.status}")
            
            return Response(
                SettlementDetailSerializer(updated_settlement).data,
                status=status.HTTP_200_OK
            )
            
        except SettlementError as e:
            logger.warning(f"Cannot retry settlement: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except InsufficientFunds as e:
            logger.warning(f"Insufficient funds for retry: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected error retrying settlement: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while retrying the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get settlement statistics
        
        GET /api/settlements/statistics/?wallet_id=<wallet_id>&start_date=<date>&end_date=<date>
        
        Returns:
            200: Settlement statistics
        """
        logger.info(f"Getting settlement statistics for user {request.user.id}")
        
        # Get optional filters
        wallet_id = request.query_params.get('wallet_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        wallet = None
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        
        # Initialize settlement service
        settlement_service = SettlementService()
        
        try:
            # Get statistics
            stats = settlement_service.get_settlement_statistics(
                wallet=wallet,
                start_date=start_date,
                end_date=end_date
            )
            
            logger.info(f"Settlement statistics calculated: {stats}")
            
            return Response(stats, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting statistics: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while calculating statistics")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==========================================
# SETTLEMENT SCHEDULE VIEWSET
# ==========================================


class SettlementScheduleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for settlement schedules
    
    Provides CRUD operations for settlement schedules with custom actions.
    
    List/Retrieve: GET /api/settlement-schedules/
    Create: POST /api/settlement-schedules/
    Update: PUT/PATCH /api/settlement-schedules/{id}/
    Delete: DELETE /api/settlement-schedules/{id}/
    Activate: POST /api/settlement-schedules/{id}/activate/
    Deactivate: POST /api/settlement-schedules/{id}/deactivate/
    Recalculate: POST /api/settlement-schedules/{id}/recalculate/
    """
    
    serializer_class = SettlementScheduleSerializer
    permission_classes = [permissions.IsAuthenticated, IsSettlementOwner]
    filterset_fields = ['is_active', 'schedule_type']
    search_fields = ['bank_account__account_number']
    ordering_fields = ['created_at', 'next_settlement']
    
    def get_queryset(self):
        """
        Get settlement schedules for the current user's wallets with optimized queries
        
        Returns:
            QuerySet: Filtered and optimized settlement schedule queryset
        """
        user = self.request.user
        
        # Get user's wallets
        user_wallets = Wallet.objects.filter(user=user)
        
        # Build optimized queryset
        queryset = SettlementSchedule.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank'
        ).order_by('-created_at')
        
        # Apply additional filters from query parameters
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        schedule_type = self.request.query_params.get('schedule_type')
        if schedule_type:
            queryset = queryset.filter(schedule_type=schedule_type)
        
        logger.debug(
            f"Settlement schedule queryset for user {user.id}: "
            f"{queryset.count()} schedules"
        )
        
        return queryset
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action
        
        Returns:
            Serializer class: Appropriate serializer for the action
        """
        action_serializers = {
            'list': SettlementScheduleListSerializer,
            'create': SettlementScheduleCreateSerializer,
            'update': SettlementScheduleUpdateSerializer,
            'partial_update': SettlementScheduleUpdateSerializer,
        }
        
        return action_serializers.get(self.action, self.serializer_class)
    
    def create(self, request, *args, **kwargs):
        """
        Create a new settlement schedule
        
        POST /api/settlement-schedules/?wallet_id=<wallet_id>
        
        Body:
        {
            "bank_account_id": "uuid",
            "schedule_type": "daily|weekly|monthly|threshold|manual",
            "is_active": true,
            "amount_threshold": "1000.00" (for threshold type),
            "minimum_amount": "100.00",
            "maximum_amount": "5000.00" (optional),
            "day_of_week": 0-6 (for weekly),
            "day_of_month": 1-31 (for monthly),
            "time_of_day": "14:00:00" (optional)
        }
        
        Returns:
            201: Schedule created
            400: Bad request (validation errors)
        """
        logger.info(f"Creating settlement schedule for user {request.user.id}")
        
        # Validate request data
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get wallet from query parameter
        wallet_id = request.query_params.get('wallet_id')
        
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            # Get default wallet
            wallet = Wallet.objects.filter(user=request.user).first()
            if not wallet:
                logger.warning(f"No wallet found for user {request.user.id}")
                return Response(
                    {"detail": _("No wallet found")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Get validated data
        validated_data = serializer.validated_data
        
        # Get bank account
        bank_account = get_object_or_404(
            BankAccount,
            id=validated_data['bank_account_id'],
            wallet=wallet
        )
        
        # Convert decimal amounts to Money objects
        amount_threshold = None
        if validated_data.get('amount_threshold'):
            amount_threshold = Money(
                validated_data['amount_threshold'],
                wallet.balance.currency
            )
        
        minimum_amount = Money(
            validated_data.get('minimum_amount', 0),
            wallet.balance.currency
        )
        
        maximum_amount = None
        if validated_data.get('maximum_amount'):
            maximum_amount = Money(
                validated_data['maximum_amount'],
                wallet.balance.currency
            )
        
        # Initialize settlement service
        settlement_service = SettlementService()
        
        try:
            # Create settlement schedule
            schedule = settlement_service.create_settlement_schedule(
                wallet=wallet,
                bank_account=bank_account,
                schedule_type=validated_data['schedule_type'],
                amount_threshold=amount_threshold,
                minimum_amount=minimum_amount,
                maximum_amount=maximum_amount,
                day_of_week=validated_data.get('day_of_week'),
                day_of_month=validated_data.get('day_of_month'),
                time_of_day=validated_data.get('time_of_day')
            )
            
            logger.info(
                f"Settlement schedule {schedule.id} created for user {request.user.id}"
            )
            
            # Return created schedule
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Error creating settlement schedule: {str(e)}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """
        Activate a settlement schedule
        
        POST /api/settlement-schedules/{id}/activate/
        
        Returns:
            200: Schedule activated
            404: Schedule not found
        """
        schedule = self.get_object()
        
        logger.info(f"Activating settlement schedule {schedule.id}")
        
        try:
            schedule.activate()
            
            logger.info(f"Settlement schedule {schedule.id} activated")
            
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"Error activating schedule: {str(e)}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """
        Deactivate a settlement schedule
        
        POST /api/settlement-schedules/{id}/deactivate/
        
        Returns:
            200: Schedule deactivated
            404: Schedule not found
        """
        schedule = self.get_object()
        
        logger.info(f"Deactivating settlement schedule {schedule.id}")
        
        try:
            schedule.deactivate()
            
            logger.info(f"Settlement schedule {schedule.id} deactivated")
            
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"Error deactivating schedule: {str(e)}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def recalculate(self, request, pk=None):
        """
        Recalculate next settlement date
        
        POST /api/settlement-schedules/{id}/recalculate/
        
        Returns:
            200: Next settlement recalculated
            400: Bad request (only for time-based schedules)
            404: Schedule not found
        """
        schedule = self.get_object()
        
        logger.info(f"Recalculating next settlement for schedule {schedule.id}")
        
        try:
            # Only recalculate for time-based schedules
            if schedule.is_time_based:
                schedule.calculate_next_settlement()
                
                logger.info(
                    f"Next settlement recalculated for schedule {schedule.id}: "
                    f"{schedule.next_settlement}"
                )
                
                return Response(
                    SettlementScheduleSerializer(schedule).data,
                    status=status.HTTP_200_OK
                )
            else:
                logger.warning(
                    f"Cannot recalculate for {schedule.schedule_type} schedule"
                )
                return Response(
                    {"detail": _("Only time-based schedules can be recalculated")},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error recalculating schedule: {str(e)}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )