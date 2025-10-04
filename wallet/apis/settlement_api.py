from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404

from wallet.models import Settlement, SettlementSchedule, BankAccount, Wallet
from wallet.serializers.settlement_serializer import (
    SettlementSerializer, SettlementDetailSerializer, SettlementCreateSerializer,
    SettlementScheduleSerializer, SettlementScheduleCreateSerializer
)
from wallet.services.settlement_service import SettlementService


class IsSettlementOwner(permissions.BasePermission):
    """Permission to check if user is the settlement owner"""
    
    def has_object_permission(self, request, view, obj):
        return obj.wallet.user == request.user


class SettlementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for settlements
    """
    serializer_class = SettlementSerializer
    permission_classes = [permissions.IsAuthenticated, IsSettlementOwner]
    
    def get_queryset(self):
        """Get settlements for the current user's wallets"""
        user_wallets = Wallet.objects.filter(user=self.request.user)
        return Settlement.objects.filter(wallet__in=user_wallets)
    
    def get_serializer_class(self):
        """Return the appropriate serializer based on action"""
        if self.action == 'retrieve':
            return SettlementDetailSerializer
        elif self.action == 'create':
            return SettlementCreateSerializer
        
        return self.serializer_class
    
    @action(detail=False, methods=['post'])
    def create_settlement(self, request):
        """
        Create a new settlement
        """
        # Get wallet first
        wallet_id = request.query_params.get('wallet_id')
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            # Get default wallet
            wallet = Wallet.objects.filter(user=request.user).first()
            if not wallet:
                return Response(
                    {"detail": _("No wallet found")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Pass wallet to serializer for validation
        serializer = SettlementCreateSerializer(data=request.data, wallet=wallet)
        serializer.is_valid(raise_exception=True)
        
        # Get bank account (we know it exists and is valid from serializer)
        bank_account = BankAccount.objects.get(
            id=serializer.validated_data['bank_account_id']
        )
        
        settlement_service = SettlementService()
        
        try:
            # Create settlement
            settlement = settlement_service.create_settlement(
                wallet=wallet,
                bank_account=bank_account,
                amount=serializer.validated_data['amount'],
                reason=serializer.validated_data.get('reason'),
                metadata=serializer.validated_data.get('metadata')
            )
            
            # Return created settlement
            return Response(
                SettlementDetailSerializer(settlement).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """
        Verify a settlement with Paystack
        """
        settlement = self.get_object()
        settlement_service = SettlementService()
        
        try:
            # Verify settlement
            updated_settlement = settlement_service.verify_settlement(settlement)
            
            # Return verified settlement
            return Response(
                SettlementDetailSerializer(updated_settlement).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class SettlementScheduleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for settlement schedules
    """
    serializer_class = SettlementScheduleSerializer
    permission_classes = [permissions.IsAuthenticated, IsSettlementOwner]
    
    def get_queryset(self):
        """Get settlement schedules for the current user's wallets"""
        user_wallets = Wallet.objects.filter(user=self.request.user)
        return SettlementSchedule.objects.filter(wallet__in=user_wallets)
    
    def get_serializer_class(self):
        """Return the appropriate serializer based on action"""
        if self.action == 'create':
            return SettlementScheduleCreateSerializer
        
        return self.serializer_class
    
    def create(self, request, *args, **kwargs):
        """Create a new settlement schedule"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get wallet and bank account
        wallet_id = request.query_params.get('wallet_id')
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            # Get default wallet
            wallet = Wallet.objects.filter(user=request.user).first()
            if not wallet:
                return Response(
                    {"detail": _("No wallet found")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        bank_account = get_object_or_404(
            BankAccount,
            id=serializer.validated_data['bank_account_id'],
            wallet=wallet
        )
        
        settlement_service = SettlementService()
        
        try:
            # Create settlement schedule
            schedule = settlement_service.create_settlement_schedule(
                wallet=wallet,
                bank_account=bank_account,
                schedule_type=serializer.validated_data['schedule_type'],
                amount_threshold=serializer.validated_data.get('amount_threshold'),
                minimum_amount=serializer.validated_data.get('minimum_amount'),
                maximum_amount=serializer.validated_data.get('maximum_amount'),
                day_of_week=serializer.validated_data.get('day_of_week'),
                day_of_month=serializer.validated_data.get('day_of_month'),
                time_of_day=serializer.validated_data.get('time_of_day')
            )
            
            # Return created schedule
            return Response(
                SettlementScheduleSerializer(schedule).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def recalculate(self, request, pk=None):
        """
        Recalculate next settlement date
        """
        schedule = self.get_object()
        
        try:
            # Only recalculate for scheduled settlements
            if schedule.schedule_type in ['daily', 'weekly', 'monthly']:
                schedule.calculate_next_settlement()
                return Response(
                    SettlementScheduleSerializer(schedule).data,
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {"detail": _("Only scheduled settlements can be recalculated")},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )