"""
Django Paystack Wallet - Bank Account API
Comprehensive REST API for bank account management
"""
import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.db.models import Count, Sum, Q
from django.db import transaction as db_transaction

from wallet.models import BankAccount, Bank, Wallet
from wallet.serializers.bank_account_serializer import (
    BankAccountSerializer,
    BankAccountListSerializer,
    BankAccountDetailSerializer,
    BankAccountCreateSerializer,
    BankAccountUpdateSerializer,
    BankAccountVerifySerializer,
    BankAccountSetDefaultSerializer,
    BankAccountStatisticsSerializer,
    BankSerializer,
    BankDetailSerializer
)
from wallet.services.wallet_service import WalletService
from wallet.exceptions import BankAccountError
from wallet.constants import TRANSACTION_STATUS_SUCCESS, SETTLEMENT_STATUS_SUCCESS


# Configure logging
logger = logging.getLogger(__name__)


# ==========================================
# PERMISSIONS
# ==========================================

class IsBankAccountOwner(permissions.BasePermission):
    """
    Permission to check if user is the bank account owner
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if request user owns the bank account"""
        return obj.wallet.user == request.user


# ==========================================
# BANK ACCOUNT VIEWSET
# ==========================================

class BankAccountViewSet(viewsets.ModelViewSet):
    """
    API endpoint for bank account management
    
    Provides CRUD operations for bank accounts plus custom actions for
    verification, default setting, and statistics.
    
    list:
        List all bank accounts for the authenticated user's wallets
        with optional filtering by wallet, bank, status, etc.
    
    retrieve:
        Get detailed information about a specific bank account
    
    create:
        Add a new bank account to a wallet (with Paystack verification)
    
    update:
        Update bank account information
    
    partial_update:
        Partially update bank account information
    
    destroy:
        Remove a bank account (soft delete - marks as inactive)
    
    verify:
        Verify bank account details with Paystack
    
    set_default:
        Set a bank account as the default for its wallet
    
    statistics:
        Get comprehensive statistics for a bank account
    
    activate:
        Activate an inactive bank account
    
    deactivate:
        Deactivate a bank account
    """
    
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated, IsBankAccountOwner]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    
    def __init__(self, **kwargs):
        """Initialize with wallet service"""
        super().__init__(**kwargs)
        self.wallet_service = WalletService()
    
    def get_queryset(self):
        """
        Get bank accounts for the current user's wallets with optimized queries
        
        Returns:
            QuerySet: Filtered and optimized bank account queryset
        """
        user = self.request.user
        
        # Get user's wallets
        user_wallets = Wallet.objects.filter(user=user)
        
        # Base queryset with optimized relations
        queryset = BankAccount.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user',
            'bank'
        ).order_by('-is_default', '-created_at')
        
        # Apply filters from query parameters
        wallet_id = self.request.query_params.get('wallet_id')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)
        
        bank_id = self.request.query_params.get('bank_id')
        if bank_id:
            queryset = queryset.filter(bank_id=bank_id)
        
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        is_verified = self.request.query_params.get('is_verified')
        if is_verified is not None:
            queryset = queryset.filter(is_verified=is_verified.lower() == 'true')
        
        is_default = self.request.query_params.get('is_default')
        if is_default is not None:
            queryset = queryset.filter(is_default=is_default.lower() == 'true')
        
        account_type = self.request.query_params.get('account_type')
        if account_type:
            queryset = queryset.filter(account_type=account_type)
        
        # Search functionality
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.search(search)
        
        logger.debug(
            f"Bank account queryset for user {user.id}: {queryset.count()} accounts"
        )
        
        return queryset
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action
        
        Returns:
            Serializer class
        """
        if self.action == 'list':
            return BankAccountListSerializer
        elif self.action == 'retrieve':
            return BankAccountDetailSerializer
        elif self.action == 'create':
            return BankAccountCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BankAccountUpdateSerializer
        elif self.action == 'verify':
            return BankAccountVerifySerializer
        elif self.action == 'set_default':
            return BankAccountSetDefaultSerializer
        elif self.action == 'statistics':
            return BankAccountStatisticsSerializer
        
        return self.serializer_class
    
    @db_transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a new bank account with Paystack verification
        
        Args:
            request: HTTP request
            
        Returns:
            Response: Created bank account data
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
            # Add context for validation
            serializer.context['wallet'] = wallet
            
            # Create bank account using wallet service
            bank_account = self.wallet_service.add_bank_account(
                wallet=wallet,
                bank_code=serializer.validated_data['bank_code'],
                account_number=serializer.validated_data['account_number'],
                account_name=serializer.validated_data.get('account_name'),
                account_type=serializer.validated_data.get('account_type'),
                bvn=serializer.validated_data.get('bvn'),
            )
            
            # Update is_default if specified
            if serializer.validated_data.get('is_default'):
                bank_account.set_as_default()
            
            logger.info(
                f"Bank account created: {bank_account.id} for wallet {wallet.id}"
            )
            
            # Return created bank account
            return Response(
                BankAccountDetailSerializer(bank_account).data,
                status=status.HTTP_201_CREATED
            )
        
        except BankAccountError as e:
            logger.error(f"Bank account creation failed: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(
                f"Unexpected error creating bank account: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": _("An error occurred while creating the bank account")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @db_transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """
        Remove a bank account (soft delete)
        
        Args:
            request: HTTP request
            
        Returns:
            Response: No content
        """
        bank_account = self.get_object()
        
        try:
            # Soft delete
            bank_account.remove()
            
            logger.info(f"Bank account {bank_account.id} marked as inactive")
            
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except Exception as e:
            logger.error(
                f"Error removing bank account {bank_account.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": _("An error occurred while removing the bank account")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def verify(self, request):
        """
        Verify bank account details with Paystack
        
        This action verifies account number and bank code with Paystack
        to retrieve the account name before adding the account.
        
        Args:
            request: HTTP request with account_number and bank_code
            
        Returns:
            Response: Verified account data
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Verify account details
            account_data = self.wallet_service.verify_bank_account(
                account_number=serializer.validated_data['account_number'],
                bank_code=serializer.validated_data['bank_code']
            )
            
            logger.info(
                f"Bank account verified: {serializer.validated_data['account_number']}"
            )
            
            return Response(account_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Bank account verification failed: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def set_default(self, request, pk=None):
        """
        Set bank account as default for its wallet
        
        Args:
            request: HTTP request
            pk: Bank account ID
            
        Returns:
            Response: Success message
        """
        bank_account = self.get_object()
        
        try:
            bank_account.set_as_default()
            
            logger.info(f"Bank account {bank_account.id} set as default")
            
            return Response(
                {
                    "detail": _("Bank account set as default successfully"),
                    "bank_account": BankAccountSerializer(bank_account).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(
                f"Error setting bank account as default: {str(e)}",
                exc_info=True
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Get comprehensive statistics for a bank account
        
        Args:
            request: HTTP request
            pk: Bank account ID
            
        Returns:
            Response: Bank account statistics
        """
        bank_account = self.get_object()
        
        try:
            # Gather statistics
            total_transactions = bank_account.transactions.count()
            successful_transactions = bank_account.transactions.filter(
                status=TRANSACTION_STATUS_SUCCESS
            ).count()
            
            total_settlements = bank_account.settlements.count()
            successful_settlements = bank_account.settlements.filter(
                status=SETTLEMENT_STATUS_SUCCESS
            ).count()
            
            settled_amount = bank_account.settlements.filter(
                status=SETTLEMENT_STATUS_SUCCESS
            ).aggregate(total=Sum('amount'))['total']
            
            statistics = {
                'id': bank_account.id,
                'account_name': bank_account.account_name,
                'account_number': bank_account.account_number,
                'bank_name': bank_account.bank.name,
                'total_transactions': total_transactions,
                'successful_transactions': successful_transactions,
                'total_settlements': total_settlements,
                'successful_settlements': successful_settlements,
                'total_settled_amount': float(settled_amount.amount) if settled_amount else 0,
                'is_default': bank_account.is_default,
                'is_active': bank_account.is_active,
                'is_verified': bank_account.is_verified,
            }
            
            return Response(statistics, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(
                f"Error getting bank account statistics: {str(e)}",
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
        Activate a bank account
        
        Args:
            request: HTTP request
            pk: Bank account ID
            
        Returns:
            Response: Success message
        """
        bank_account = self.get_object()
        
        try:
            bank_account.activate()
            
            logger.info(f"Bank account {bank_account.id} activated")
            
            return Response(
                {
                    "detail": _("Bank account activated successfully"),
                    "bank_account": BankAccountSerializer(bank_account).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(f"Error activating bank account: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def deactivate(self, request, pk=None):
        """
        Deactivate a bank account
        
        Args:
            request: HTTP request
            pk: Bank account ID
            
        Returns:
            Response: Success message
        """
        bank_account = self.get_object()
        
        try:
            bank_account.deactivate()
            
            logger.info(f"Bank account {bank_account.id} deactivated")
            
            return Response(
                {
                    "detail": _("Bank account deactivated successfully"),
                    "bank_account": BankAccountSerializer(bank_account).data
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(f"Error deactivating bank account: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

@action(detail=False, methods=['get'])
def export(self, request):
    """
    Export bank accounts to CSV, Excel, or PDF
    
    GET /api/bank-accounts/export/?format=<format>&wallet_id=<id>&bank_id=<id>&is_active=<bool>
    
    Query Parameters:
        - format: Export format ('csv', 'xlsx', or 'pdf', default: 'csv')
        - wallet_id: Filter by wallet ID (optional)
        - bank_id: Filter by bank ID (optional)
        - is_active: Filter by active status (optional)
        - is_verified: Filter by verification status (optional)
        - is_default: Filter by default status (optional)
        - account_type: Filter by account type (optional)
    
    Returns:
        HttpResponse: File download response (CSV, Excel, or PDF)
    
    Response (200):
        File download with Content-Disposition header
    
    Response Error (400):
        {
            "error": "Invalid export format. Use 'csv', 'xlsx', or 'pdf'"
        }
    
    Example Usage:
        GET /api/bank-accounts/export/?format=csv
        GET /api/bank-accounts/export/?format=xlsx&wallet_id=123&is_verified=true
        GET /api/bank-accounts/export/?format=pdf&is_active=true
    """
    try:
        # Parse parameters
        export_format = request.query_params.get('format', 'csv')
        wallet_id = request.query_params.get('wallet_id')
        bank_id = request.query_params.get('bank_id')
        is_active = request.query_params.get('is_active')
        is_verified = request.query_params.get('is_verified')
        is_default = request.query_params.get('is_default')
        account_type = request.query_params.get('account_type')
        
        # Build queryset - start with user's bank accounts
        queryset = self.get_queryset()
        
        # Apply filters
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)
        
        if bank_id:
            queryset = queryset.filter(bank_id=bank_id)
        
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        if is_verified is not None:
            queryset = queryset.filter(is_verified=is_verified.lower() == 'true')
        
        if is_default is not None:
            queryset = queryset.filter(is_default=is_default.lower() == 'true')
        
        if account_type:
            queryset = queryset.filter(account_type=account_type)
        
        # Order by creation date (most recent first)
        queryset = queryset.order_by('-created_at')
        
        # Define fields to export
        export_fields = [
            'id',
            'wallet.tag',
            'wallet.user.email',
            'bank.name',
            'bank.code',
            'account_number',
            'account_name',
            'account_type',
            'is_verified',
            'is_default',
            'is_active',
            'paystack_recipient_code',
            'created_at',
        ]
        
        # Export based on format
        if export_format == 'csv':
            from wallet.utils.exporters import export_queryset_to_csv
            
            response = export_queryset_to_csv(
                queryset=queryset,
                fields=export_fields,
                filename_prefix='bank_accounts'
            )
        elif export_format == 'xlsx':
            from wallet.utils.exporters import export_queryset_to_excel
            
            response = export_queryset_to_excel(
                queryset=queryset,
                fields=export_fields,
                filename_prefix='bank_accounts',
                sheet_name='Bank Accounts'
            )
        elif export_format == 'pdf':
            from wallet.utils.exporters import export_queryset_to_pdf
            
            response = export_queryset_to_pdf(
                queryset=queryset,
                fields=export_fields,
                filename_prefix='bank_accounts',
                title='Bank Account Records'
            )
        else:
            return Response(
                {'error': _("Invalid export format. Use 'csv', 'xlsx', or 'pdf'")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        logger.info(
            f"Exported {queryset.count()} bank accounts to {export_format} "
            f"for user {request.user.id}"
        )
        
        return response
    
    except Exception as e:
        logger.error(
            f"Export failed for user {request.user.id}: {str(e)}",
            exc_info=True
        )
        return Response(
            {'error': _("Export failed")},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# ==========================================
# BANK VIEWSET
# ==========================================

class BankViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing available banks
    
    Provides read-only access to the list of banks supported by Paystack.
    
    list:
        List all available banks with optional filtering by country, currency
    
    retrieve:
        Get detailed information about a specific bank
    """
    
    serializer_class = BankSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'head', 'options']
    
    def get_queryset(self):
        """
        Get all active banks with optional filtering
        
        Returns:
            QuerySet: Filtered bank queryset
        """
        queryset = Bank.objects.active().order_by('name')
        
        # Apply filters from query parameters
        country = self.request.query_params.get('country')
        if country:
            queryset = queryset.by_country(country)
        
        currency = self.request.query_params.get('currency')
        if currency:
            queryset = queryset.by_currency(currency)
        
        # Search functionality
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.search(search)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'retrieve':
            return BankDetailSerializer
        return self.serializer_class