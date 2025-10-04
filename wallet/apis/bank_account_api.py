from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404

from wallet.models import BankAccount, Bank, Wallet
from wallet.serializers.bank_account_serializer import (
    BankAccountSerializer, BankAccountDetailSerializer, BankAccountCreateSerializer,
    BankAccountUpdateSerializer, BankAccountVerifySerializer, BankSerializer
)
from wallet.services.wallet_service import WalletService


class IsBankAccountOwner(permissions.BasePermission):
    """Permission to check if user is the bank account owner"""
    
    def has_object_permission(self, request, view, obj):
        return obj.wallet.user == request.user


class BankAccountViewSet(viewsets.ModelViewSet):
    """
    API endpoint for bank accounts
    """
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated, IsBankAccountOwner]
    
    def get_queryset(self):
        """Get bank accounts for the current user's wallets"""
        user_wallets = Wallet.objects.filter(user=self.request.user)
        return BankAccount.objects.filter(wallet__in=user_wallets)
    
    def get_serializer_class(self):
        """Return the appropriate serializer based on action"""
        if self.action == 'retrieve':
            return BankAccountDetailSerializer
        elif self.action == 'create':
            return BankAccountCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BankAccountUpdateSerializer
        elif self.action == 'verify':
            return BankAccountVerifySerializer
        
        return self.serializer_class
    
    def create(self, request, *args, **kwargs):
        """Create a new bank account"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wallet_service = WalletService()  # Define wallet_service here
        # Get wallet
        wallet_id = request.query_params.get('wallet_id')
        if wallet_id:
            wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        else:
            # Get or create default wallet
            wallet = wallet_service.get_wallet(request.user)
        try:
            # Create bank account using wallet service
            bank_account = wallet_service.add_bank_account(
                wallet=wallet,
                bank_code=serializer.validated_data['bank_code'],
                account_number=serializer.validated_data['account_number'],
                account_name=serializer.validated_data.get('account_name'),
                account_type=serializer.validated_data.get('account_type'),
                bvn = serializer.validated_data.get('bvn'),
            )
            # Update is_default if specified
            if serializer.validated_data.get('is_default'):
                bank_account.set_as_default()
            # Return created bank account
            return Response(
                BankAccountDetailSerializer(bank_account).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def destroy(self, request, *args, **kwargs):
        """Remove a bank account"""
        bank_account = self.get_object()
        
        # Instead of deletion, mark as inactive
        bank_account.remove()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=False, methods=['post'])
    def verify(self, request):
        """
        Verify bank account details
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        
        try:
            # Verify account details
            account_data = wallet_service.verify_bank_account(
                account_number=serializer.validated_data['account_number'],
                bank_code=serializer.validated_data['bank_code']
            )
            
            return Response(account_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """
        Set bank account as default
        """
        bank_account = self.get_object()
        
        try:
            bank_account.set_as_default()
            return Response(
                {"detail": _("Bank account set as default successfully")},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class BankViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for banks
    """
    queryset = Bank.objects.filter(is_active=True)
    serializer_class = BankSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def refresh(self, request):
        """
        Refresh bank list from Paystack
        """
        wallet_service = WalletService()
        
        try:
            # Get banks from Paystack
            banks_data = wallet_service.list_banks()
            
            # Update or create banks
            for bank_data in banks_data:
                bank_code = bank_data.get('code')
                if not bank_code:
                    continue
                    
                Bank.objects.update_or_create(
                    code=bank_code,
                    defaults={
                        'name': bank_data.get('name', ''),
                        'slug': bank_data.get('slug', bank_code.lower()),
                        'country': bank_data.get('country', 'NG'),
                        'currency': bank_data.get('currency', 'NGN'),
                        'type': bank_data.get('type'),
                        'is_active': bank_data.get('active', True),
                        'paystack_data': bank_data
                    }
                )
            
            # Return updated bank list
            banks = Bank.objects.filter(is_active=True)
            serializer = self.get_serializer(banks, many=True)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )