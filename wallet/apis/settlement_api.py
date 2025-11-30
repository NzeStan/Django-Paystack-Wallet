import logging
from decimal import Decimal
from typing import Optional
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from djmoney.money import Money
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
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
    FinalizeSettlementSerializer,
    SettlementScheduleSerializer,
    SettlementScheduleCreateSerializer,
    SettlementScheduleUpdateSerializer,
    SettlementScheduleListSerializer
)
from wallet.services.settlement_service import SettlementService
from wallet.exceptions import (
    SettlementError,
    InsufficientFunds,
    WalletLocked,
    PaystackAPIError
)


logger = logging.getLogger(__name__)


# ==========================================
# PERMISSIONS
# ==========================================


class IsSettlementOwner(permissions.BasePermission):
    """
    Permission to check if user is the settlement owner
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user owns the settlement"""
        return obj.wallet.user == request.user


class IsScheduleOwner(permissions.BasePermission):
    """
    Permission to check if user is the schedule owner
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user owns the schedule"""
        return obj.wallet.user == request.user


# ==========================================
# SETTLEMENT VIEWSET (COMPLETE)
# ==========================================


class SettlementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for settlements with OTP support and statistics
    
    Provides read-only access to settlements with custom actions for:
    - Creating settlements (with OTP detection)
    - Finalizing settlements with OTP
    - Verifying settlement status
    - Retrying failed settlements
    - Getting settlement statistics
    - Getting settlement summaries
    - Getting top settlement destinations
    
    Endpoints:
    List/Retrieve: GET /api/settlements/
    Create: POST /api/settlements/create_settlement/
    Finalize (OTP): POST /api/settlements/{id}/finalize-settlement/
    Verify: GET /api/settlements/{id}/verify/
    Retry: POST /api/settlements/{id}/retry/
    Statistics: GET /api/settlements/statistics/
    Summary: GET /api/settlements/summary/
    Top Destinations: GET /api/settlements/top-destinations/
    """
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]
    serializer_class = SettlementSerializer
    permission_classes = [permissions.IsAuthenticated, IsSettlementOwner]
    filterset_fields = ['status', 'bank_account']
    search_fields = ['reference', 'paystack_transfer_code', 'reason']
    ordering_fields = ['created_at', 'settled_at', 'amount']
    
    def get_queryset(self):
        user = self.request.user
        user_wallets = Wallet.objects.filter(user=user)
        
        # ✅ Just return base queryset - filters handle the rest
        queryset = Settlement.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank',
            'transaction'
        ).order_by('-created_at')
        
        # ✅ Remove manual filter handling - DjangoFilterBackend does it
        # No longer need status_filter, bank_account_filter manually
        
        # ✅ Keep date range filters (custom logic)
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        action_serializers = {
            'list': SettlementListSerializer,
            'retrieve': SettlementDetailSerializer,
            'create_settlement': SettlementCreateSerializer,
            'finalize_settlement': FinalizeSettlementSerializer,
            'update': SettlementUpdateSerializer,
            'partial_update': SettlementUpdateSerializer,
        }
        
        return action_serializers.get(self.action, self.serializer_class)
    
    # ==========================================
    # CREATE SETTLEMENT
    # ==========================================
    
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
        
        Response Success (201):
        {
            "status": "success",
            "message": "Settlement initiated successfully",
            "settlement": {...},
            "transfer": {
                "transfer_code": "TRF_xxxxx",
                "status": "success",
                "requires_otp": false
            }
        }
        
        Response OTP Required (201):
        {
            "status": "pending_otp",
            "message": "OTP required to complete settlement",
            "settlement": {...},
            "transfer": {
                "transfer_code": "TRF_xxxxx",
                "status": "otp",
                "requires_otp": true
            }
        }
        """
        logger.info(f"Creating settlement for user {request.user.id}")
        
        # Get wallet
        wallet_id = request.query_params.get('wallet_id')
        
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            wallet = Wallet.objects.filter(user=request.user).first()
            if not wallet:
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
        
        # Create Money object
        amount = Money(
            validated_data['amount'],
            wallet.balance.currency
        )
        
        # Initialize service
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
            
            logger.info(f"Settlement {settlement.id} created for user {request.user.id}")
            
            # Prepare response
            response_data = {
                'settlement': SettlementDetailSerializer(settlement).data
            }
            
            # Check if OTP required
            if settlement.paystack_transfer_data:
                requires_otp = settlement.paystack_transfer_data.get('requires_otp', False)
                transfer_status = settlement.paystack_transfer_data.get('status', 'pending')
                
                response_data['transfer'] = {
                    'transfer_code': settlement.paystack_transfer_code,
                    'status': transfer_status,
                    'requires_otp': requires_otp
                }
                
                if requires_otp or transfer_status == 'otp':
                    response_data['status'] = 'pending_otp'
                    response_data['message'] = _(
                        'OTP required to complete settlement. '
                        'Please check your phone for OTP and call finalize-settlement endpoint.'
                    )
                else:
                    response_data['status'] = 'success'
                    response_data['message'] = _('Settlement initiated successfully')
            else:
                response_data['status'] = 'pending'
                response_data['message'] = _('Settlement created and pending processing')
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except WalletLocked as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except InsufficientFunds as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except SettlementError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except PaystackAPIError as e:
            logger.error(f"Paystack API error: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("Payment gateway error. Please try again later.")},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while creating the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # FINALIZE SETTLEMENT (NEW - OTP)
    # ==========================================
    
    @action(detail=True, methods=['post'], url_path='finalize-settlement')
    def finalize_settlement(self, request, pk=None):
        """
        Finalize a pending settlement with OTP
        
        POST /api/settlements/{id}/finalize-settlement/
        
        Request Body:
        {
            "otp": "123456"
        }
        
        Response Success (200):
        {
            "status": "success",
            "message": "Settlement completed successfully",
            "settlement": {...}
        }
        """
        settlement = self.get_object()
        
        # Validate OTP provided
        otp = request.data.get('otp')
        if not otp:
            return Response(
                {"detail": _("OTP is required")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        logger.info(f"Finalizing settlement {settlement.id} with OTP")
        
        settlement_service = SettlementService()
        
        try:
            # Finalize with OTP
            finalize_data = settlement_service.finalize_settlement(
                settlement=settlement,
                otp=otp
            )
            
            # Refresh settlement
            settlement.refresh_from_db()
            
            # Prepare response
            response_data = {
                'settlement': SettlementDetailSerializer(settlement).data
            }
            
            # Check final status
            if settlement.is_completed and settlement.status == 'success':
                response_data['status'] = 'success'
                response_data['message'] = _('Settlement completed successfully')
                return Response(response_data, status=status.HTTP_200_OK)
                
            elif settlement.status == 'failed':
                response_data['status'] = 'failed'
                response_data['message'] = _('Settlement finalization failed')
                return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
            else:
                response_data['status'] = 'processing'
                response_data['message'] = _('Settlement is being processed')
                return Response(response_data, status=status.HTTP_202_ACCEPTED)
                
        except SettlementError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except PaystackAPIError as e:
            logger.error(f"Paystack API error: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("Payment gateway error. Please try again later.")},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while finalizing the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # VERIFY SETTLEMENT
    # ==========================================
    
    @action(detail=True, methods=['get'])
    def verify(self, request, pk=None):
        """
        Verify a settlement's status with Paystack
        
        GET /api/settlements/{id}/verify/
        """
        settlement = self.get_object()
        
        logger.info(f"Verifying settlement {settlement.id}")
        
        settlement_service = SettlementService()
        
        try:
            updated_settlement = settlement_service.verify_settlement(settlement)
            
            return Response(
                SettlementDetailSerializer(updated_settlement).data,
                status=status.HTTP_200_OK
            )
            
        except SettlementError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while verifying the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # RETRY SETTLEMENT
    # ==========================================
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retry a failed settlement
        
        POST /api/settlements/{id}/retry/
        """
        settlement = self.get_object()
        
        logger.info(f"Retrying settlement {settlement.id}")
        
        settlement_service = SettlementService()
        
        try:
            updated_settlement = settlement_service.retry_settlement(settlement)
            
            return Response(
                SettlementDetailSerializer(updated_settlement).data,
                status=status.HTTP_200_OK
            )
            
        except SettlementError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except InsufficientFunds as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while retrying the settlement")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # STATISTICS (NEW!)
    # ==========================================
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get settlement statistics
        
        GET /api/settlements/statistics/?wallet_id=<wallet_id>&start_date=<date>&end_date=<date>
        
        Query Parameters:
        - wallet_id: Filter by wallet (optional)
        - start_date: Start date (YYYY-MM-DD) (optional)
        - end_date: End date (YYYY-MM-DD) (optional)
        
        Response (200):
        {
            "total_count": 100,
            "total_amount": 50000.00,
            "average_amount": 500.00,
            "successful_count": 95,
            "failed_count": 3,
            "pending_count": 2,
            "success_rate": 95.0,
            "recent_settlements": [...]
        }
        """
        logger.info(f"Getting settlement statistics for user {request.user.id}")
        
        settlement_service = SettlementService()
        
        # Get optional filters
        wallet_id = request.query_params.get('wallet_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        # Parse dates if provided
        start_datetime = None
        end_datetime = None
        
        if start_date:
            try:
                start_datetime = timezone.datetime.strptime(start_date, '%Y-%m-%d')
                start_datetime = timezone.make_aware(start_datetime)
            except ValueError:
                return Response(
                    {"detail": _("Invalid start_date format. Use YYYY-MM-DD")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if end_date:
            try:
                end_datetime = timezone.datetime.strptime(end_date, '%Y-%m-%d')
                end_datetime = timezone.make_aware(end_datetime)
            except ValueError:
                return Response(
                    {"detail": _("Invalid end_date format. Use YYYY-MM-DD")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Get wallet if specified
        wallet = None
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        
        try:
            # Get statistics
            stats = settlement_service.get_settlement_stats(
                wallet=wallet,
                start_date=start_datetime,
                end_date=end_datetime
            )
            
            logger.info(
                f"Retrieved settlement statistics: {stats['total_count']} total settlements"
            )
            
            return Response(stats, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting statistics: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while retrieving statistics")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # SUMMARY (NEW!)
    # ==========================================
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Get settlement summary for a wallet
        
        GET /api/settlements/summary/?wallet_id=<wallet_id>&period_days=<days>
        
        Query Parameters:
        - wallet_id: Wallet ID (required)
        - period_days: Number of days to include (default: 30)
        
        Response (200):
        {
            "total_settled": 10000.00,
            "settlement_count": 20,
            "pending_count": 2,
            "failed_count": 1,
            "period_days": 30,
            "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2024-01-31T23:59:59Z"
        }
        """
        logger.info(f"Getting settlement summary for user {request.user.id}")
        
        # Get wallet ID (required)
        wallet_id = request.query_params.get('wallet_id')
        if not wallet_id:
            return Response(
                {"detail": _("wallet_id is required")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get wallet
        wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        
        # Get period_days (default 30)
        period_days = int(request.query_params.get('period_days', 30))
        
        if period_days < 1 or period_days > 365:
            return Response(
                {"detail": _("period_days must be between 1 and 365")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        settlement_service = SettlementService()
        
        try:
            # Get summary
            summary = settlement_service.get_settlement_summary(
                wallet=wallet,
                period_days=period_days
            )
            
            logger.info(
                f"Retrieved settlement summary for wallet {wallet.id}: "
                f"{summary['settlement_count']} settlements"
            )
            
            return Response(summary, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting summary: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while retrieving summary")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # TOP DESTINATIONS (NEW!)
    # ==========================================
    
    @action(detail=False, methods=['get'], url_path='top-destinations')
    def top_destinations(self, request):
        """
        Get top settlement destinations for a wallet
        
        GET /api/settlements/top-destinations/?wallet_id=<wallet_id>&limit=<limit>
        
        Query Parameters:
        - wallet_id: Wallet ID (required)
        - limit: Number of results (default: 5, max: 20)
        
        Response (200):
        [
            {
                "bank_account__id": "uuid",
                "bank_account__account_name": "John Doe",
                "bank_account__account_number": "0123456789",
                "bank_account__bank__name": "GTBank",
                "settlement_count": 10,
                "total_amount": 50000.00
            },
            ...
        ]
        """
        logger.info(f"Getting top settlement destinations for user {request.user.id}")
        
        # Get wallet ID (required)
        wallet_id = request.query_params.get('wallet_id')
        if not wallet_id:
            return Response(
                {"detail": _("wallet_id is required")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get wallet
        wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        
        # Get limit (default 5, max 20)
        limit = int(request.query_params.get('limit', 5))
        limit = min(max(limit, 1), 20)  # Clamp between 1 and 20
        
        settlement_service = SettlementService()
        
        try:
            # Get top destinations
            destinations = settlement_service.get_top_settlement_destinations(
                wallet=wallet,
                limit=limit
            )
            
            logger.info(
                f"Retrieved {len(destinations)} top settlement destinations "
                f"for wallet {wallet.id}"
            )
            
            return Response(destinations, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting top destinations: {str(e)}", exc_info=True)
            return Response(
                {"detail": _("An error occurred while retrieving top destinations")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==========================================
# SETTLEMENT SCHEDULE VIEWSET
# ==========================================


class SettlementScheduleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for settlement schedules
    
    Standard REST Endpoints:
        POST /api/settlement-schedules/ - Create schedule
        GET /api/settlement-schedules/ - List schedules
        GET /api/settlement-schedules/{id}/ - Retrieve schedule
        PUT/PATCH /api/settlement-schedules/{id}/ - Update schedule
        DELETE /api/settlement-schedules/{id}/ - Delete schedule
    
    Custom Actions:
        POST /api/settlement-schedules/{id}/activate/ - Activate schedule
        POST /api/settlement-schedules/{id}/deactivate/ - Deactivate schedule
    """
    
    serializer_class = SettlementScheduleSerializer
    permission_classes = [permissions.IsAuthenticated, IsScheduleOwner]
    
    # ✅ Add filter backends
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]
    
    filterset_fields = ['is_active', 'schedule_type', 'bank_account']
    search_fields = ['schedule_type']
    ordering_fields = ['created_at', 'next_settlement']
    
    def get_queryset(self):
        """Get settlement schedules for the current user's wallets"""
        user = self.request.user
        user_wallets = Wallet.objects.filter(user=user)
        
        queryset = SettlementSchedule.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank'
        ).order_by('-created_at')
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        action_serializers = {
            'list': SettlementScheduleListSerializer,
            'retrieve': SettlementScheduleSerializer,
            'create': SettlementScheduleCreateSerializer,  # ✅ Standard create
            'update': SettlementScheduleUpdateSerializer,
            'partial_update': SettlementScheduleUpdateSerializer,
        }
        
        return action_serializers.get(self.action, self.serializer_class)
    
    # ==========================================
    # STANDARD REST METHODS (✅ FIXED)
    # ==========================================
    
    def create(self, request, *args, **kwargs):
        """
        Create a new settlement schedule
        
        POST /api/settlement-schedules/
        """
        logger.info(f"Creating settlement schedule for user {request.user.id}")
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            from wallet.services.settlement_service import SettlementService
            
            settlement_service = SettlementService()
            validated_data = serializer.validated_data
            
            # Get wallet and bank account
            wallet = get_object_or_404(Wallet, id=validated_data['wallet_id'], user=request.user)
            bank_account = get_object_or_404(
                BankAccount,
                id=validated_data['bank_account_id'],
                wallet=wallet
            )
            
            # Convert amounts to Money
            amount_threshold = None
            if validated_data.get('amount_threshold'):
                amount_threshold = Money(validated_data['amount_threshold'], wallet.balance.currency)
            
            minimum_amount = Money(
                validated_data.get('minimum_amount', 0),
                wallet.balance.currency
            )
            
            maximum_amount = None
            if validated_data.get('maximum_amount'):
                maximum_amount = Money(validated_data['maximum_amount'], wallet.balance.currency)
            
            # Create schedule via service
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
            
            logger.info(f"Created settlement schedule {schedule.id}")
            
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Error creating schedule: {str(e)}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def update(self, request, *args, **kwargs):
        """
        Update a settlement schedule (full update)
        
        PUT /api/settlement-schedules/{id}/
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        # Perform update
        self.perform_update(serializer)
        
        logger.info(f"Updated settlement schedule {instance.id}")
        
        return Response(serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a settlement schedule
        
        PATCH /api/settlement-schedules/{id}/
        """
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    
    def destroy(self, request, *args, **kwargs):
        """
        Delete a settlement schedule
        
        DELETE /api/settlement-schedules/{id}/
        """
        instance = self.get_object()
        schedule_id = instance.id
        self.perform_destroy(instance)
        
        logger.info(f"Deleted settlement schedule {schedule_id}")
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    # ==========================================
    # CUSTOM ACTIONS
    # ==========================================
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a settlement schedule"""
        schedule = self.get_object()
        
        try:
            schedule.activate()
            logger.info(f"Activated settlement schedule {schedule.id}")
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error activating schedule: {str(e)}")
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a settlement schedule"""
        schedule = self.get_object()
        
        try:
            schedule.deactivate()
            logger.info(f"Deactivated settlement schedule {schedule.id}")
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error deactivating schedule: {str(e)}")
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)