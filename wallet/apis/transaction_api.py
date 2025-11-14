"""
Django Paystack Wallet - Transaction API Views
Refactored with comprehensive ViewSet, query optimization, error handling, and clean architecture
"""
import logging
from typing import Any, Dict

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.request import Request
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.http import HttpResponse

from wallet.models import Transaction, Wallet
from wallet.serializers.transaction_serializer import (
    TransactionSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
    TransactionCreateSerializer,
    TransactionVerifySerializer,
    TransactionRefundSerializer,
    TransactionCancelSerializer,
    TransactionFilterSerializer,
    TransactionStatisticsSerializer,
    TransactionSummarySerializer,
    TransactionExportSerializer
)
from wallet.services.transaction_service import TransactionService
from wallet.exceptions import (
    TransactionFailed,
    InsufficientFunds,
    InvalidAmount,
    WalletLocked
)


logger = logging.getLogger(__name__)


# ==========================================
# CUSTOM PERMISSIONS
# ==========================================

class IsTransactionOwner(permissions.BasePermission):
    """
    Permission to check if user owns the transaction's wallet
    
    Ensures that users can only access transactions from their own wallets.
    """
    
    message = _("You do not have permission to access this transaction")
    
    def has_object_permission(self, request: Request, view: Any, obj: Transaction) -> bool:
        """
        Check if user owns the transaction's wallet
        
        Args:
            request: HTTP request
            view: View instance
            obj: Transaction object to check
            
        Returns:
            bool: True if user owns the transaction's wallet
        """
        return obj.wallet.user == request.user


# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request
    
    Handles proxy headers and direct connections.
    
    Args:
        request: HTTP request
        
    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request: Request) -> str:
    """
    Extract user agent from request
    
    Args:
        request: HTTP request
        
    Returns:
        str: User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


# ==========================================
# TRANSACTION VIEWSET
# ==========================================

class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API ViewSet for transaction operations
    
    Provides read-only access to transactions with comprehensive filtering,
    statistics, and export capabilities. Transactions are automatically
    created through wallet operations (deposit, withdraw, transfer).
    
    list:
        List all transactions for the authenticated user's wallets
        with optional filtering by type, status, date range, etc.
    
    retrieve:
        Get detailed information about a specific transaction
    
    verify:
        Verify a transaction by its reference number
    
    refund:
        Initiate a refund for a completed transaction
    
    cancel:
        Cancel a pending transaction
    
    statistics:
        Get transaction statistics for user's wallets
    
    summary:
        Get a comprehensive summary of transactions
    
    export:
        Export transactions to CSV or Excel format
    """
    
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated, IsTransactionOwner]
    
    def __init__(self, **kwargs):
        """Initialize with transaction service"""
        super().__init__(**kwargs)
        self.transaction_service = TransactionService()
    
    def get_queryset(self):
        """
        Get transactions for the current user's wallets with optimized queries
        
        Returns:
            QuerySet: Optimized transaction queryset
        """
        user = self.request.user
        user_wallets = Wallet.objects.filter(user=user)
        
        # Base queryset with optimized relations
        queryset = Transaction.objects.filter(
            wallet__in=user_wallets
        ).select_related(
            'wallet',
            'wallet__user',
            'recipient_wallet',
            'recipient_wallet__user',
            'recipient_bank_account',
            'recipient_bank_account__bank',
            'card',
            'related_transaction'
        )
        
        return queryset
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action
        
        Returns:
            Serializer class
        """
        if self.action == 'retrieve':
            return TransactionDetailSerializer
        elif self.action == 'list':
            return TransactionListSerializer
        elif self.action == 'create':
            return TransactionCreateSerializer
        elif self.action == 'verify':
            return TransactionVerifySerializer
        elif self.action == 'refund':
            return TransactionRefundSerializer
        elif self.action == 'cancel':
            return TransactionCancelSerializer
        elif self.action == 'statistics':
            return TransactionStatisticsSerializer
        elif self.action == 'summary':
            return TransactionSummarySerializer
        elif self.action == 'export':
            return TransactionExportSerializer
        
        return self.serializer_class
    
    def list(self, request: Request, *args, **kwargs):
        """
        List transactions with comprehensive filtering
        
        Query Parameters:
            - wallet_id: Filter by wallet ID
            - transaction_type: Filter by transaction type
            - status: Filter by status
            - payment_method: Filter by payment method
            - reference: Filter by reference
            - start_date: Filter by start date (ISO 8601)
            - end_date: Filter by end date (ISO 8601)
            - min_amount: Filter by minimum amount
            - max_amount: Filter by maximum amount
            - limit: Results per page (default: 20, max: 100)
            - offset: Pagination offset (default: 0)
        
        Returns:
            Response: Paginated transaction list
        """
        # Parse and validate filter parameters
        filter_serializer = TransactionFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        
        # Extract validated parameters
        filters = filter_serializer.validated_data
        wallet_id = filters.get('wallet_id')
        transaction_type = filters.get('transaction_type')
        status_param = filters.get('status')
        payment_method = filters.get('payment_method')
        reference = filters.get('reference')
        start_date = filters.get('start_date')
        end_date = filters.get('end_date')
        min_amount = filters.get('min_amount')
        max_amount = filters.get('max_amount')
        limit = filters.get('limit', 20)
        offset = filters.get('offset', 0)
        
        # Build queryset with filters
        queryset = self.get_queryset()
        
        if wallet_id:
            queryset = queryset.filter(wallet__id=wallet_id)
        
        if transaction_type:
            queryset = queryset.by_type(transaction_type)
        
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)
        
        if reference:
            queryset = queryset.filter(reference__icontains=reference)
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        if min_amount is not None or max_amount is not None:
            queryset = queryset.by_amount_range(min_amount, max_amount)
        
        # Order by most recent first
        queryset = queryset.order_by('-created_at')
        
        # Get total count before pagination
        total_count = queryset.count()
        
        # Apply pagination
        queryset = queryset[offset:offset + limit]
        
        # Serialize data
        serializer = self.get_serializer(queryset, many=True)
        
        logger.info(
            f"Listed {len(serializer.data)} transactions for user {request.user.id} "
            f"(total: {total_count})"
        )
        
        # Return paginated response
        return Response({
            'count': total_count,
            'next': offset + limit if offset + limit < total_count else None,
            'previous': offset - limit if offset > 0 else None,
            'results': serializer.data
        })
    
    def retrieve(self, request: Request, pk=None):
        """
        Retrieve detailed transaction information
        
        Args:
            pk: Transaction ID
            
        Returns:
            Response: Detailed transaction data
        """
        try:
            transaction = self.get_object()
            serializer = self.get_serializer(transaction)
            
            logger.info(
                f"Retrieved transaction {transaction.id} for user {request.user.id}"
            )
            
            return Response(serializer.data)
        
        except Transaction.DoesNotExist:
            logger.warning(
                f"Transaction {pk} not found for user {request.user.id}"
            )
            return Response(
                {'error': _("Transaction not found")},
                status=status.HTTP_404_NOT_FOUND
            )
    
    # ==========================================
    # CUSTOM ACTIONS
    # ==========================================
    
    @action(detail=False, methods=['post'])
    def verify(self, request: Request):
        """
        Verify a transaction by reference
        
        Body Parameters:
            - reference: Transaction reference to verify
        
        Returns:
            Response: Transaction verification result
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        reference = serializer.validated_data['reference']
        
        try:
            transaction = self.transaction_service.get_transaction_by_reference(
                reference
            )
            
            # Check permission
            if transaction.wallet.user != request.user:
                logger.warning(
                    f"User {request.user.id} attempted to verify "
                    f"transaction {transaction.id} from another user"
                )
                return Response(
                    {'error': _("You do not have permission to verify this transaction")},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            result_serializer = TransactionDetailSerializer(transaction)
            
            logger.info(
                f"Verified transaction {transaction.id} with reference {reference}"
            )
            
            return Response(result_serializer.data)
        
        except Transaction.DoesNotExist:
            logger.error(f"Transaction with reference {reference} not found")
            return Response(
                {'error': _("Transaction not found")},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def refund(self, request: Request, pk=None):
        """
        Refund a transaction
        
        Body Parameters:
            - amount: Amount to refund (optional, defaults to full amount)
            - reason: Reason for refund (optional)
        
        Returns:
            Response: Refund transaction details
        """
        try:
            transaction = self.get_object()
            
            # Parse refund data
            amount = request.data.get('amount')
            reason = request.data.get('reason')
            
            # Perform refund
            refund_transaction = self.transaction_service.refund_transaction(
                transaction=transaction,
                amount=amount,
                reason=reason
            )
            
            refund_serializer = TransactionDetailSerializer(refund_transaction)
            
            logger.info(
                f"Created refund transaction {refund_transaction.id} for "
                f"transaction {transaction.id} by user {request.user.id}"
            )
            
            return Response(
                {
                    'message': _("Refund processed successfully"),
                    'refund': refund_serializer.data
                },
                status=status.HTTP_201_CREATED
            )
        
        except ValueError as e:
            logger.error(
                f"Refund validation error for transaction {pk}: {str(e)}"
            )
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Transaction.DoesNotExist:
            logger.warning(f"Transaction {pk} not found for refund")
            return Response(
                {'error': _("Transaction not found")},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(
                f"Refund failed for transaction {pk}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': _("Refund failed: {error}").format(error=str(e))},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    @db_transaction.atomic
    def cancel(self, request: Request, pk=None):
        """
        Cancel a pending transaction
        
        Body Parameters:
            - reason: Reason for cancellation (optional)
        
        Returns:
            Response: Cancelled transaction details
        """
        try:
            transaction = self.get_object()
            
            # Parse cancellation reason
            reason = request.data.get('reason')
            
            # Cancel transaction
            cancelled_transaction = self.transaction_service.cancel_transaction(
                transaction=transaction,
                reason=reason
            )
            
            cancel_serializer = TransactionDetailSerializer(cancelled_transaction)
            
            logger.info(
                f"Cancelled transaction {transaction.id} by user {request.user.id}"
            )
            
            return Response(
                {
                    'message': _("Transaction cancelled successfully"),
                    'transaction': cancel_serializer.data
                }
            )
        
        except ValueError as e:
            logger.error(
                f"Cancel validation error for transaction {pk}: {str(e)}"
            )
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Transaction.DoesNotExist:
            logger.warning(f"Transaction {pk} not found for cancellation")
            return Response(
                {'error': _("Transaction not found")},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(
                f"Cancellation failed for transaction {pk}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': _("Cancellation failed: {error}").format(error=str(e))},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def statistics(self, request: Request):
        """
        Get transaction statistics for user's wallets
        
        Query Parameters:
            - wallet_id: Filter by specific wallet (optional)
            - start_date: Start date for statistics (optional)
            - end_date: End date for statistics (optional)
        
        Returns:
            Response: Transaction statistics
        """
        try:
            # Parse filters
            wallet_id = request.query_params.get('wallet_id')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            
            # Get wallet if specified
            wallet = None
            if wallet_id:
                wallet = get_object_or_404(
                    Wallet,
                    id=wallet_id,
                    user=request.user
                )
            
            # Get statistics
            stats = self.transaction_service.get_transaction_statistics(
                wallet=wallet,
                start_date=start_date,
                end_date=end_date
            )
            
            serializer = self.get_serializer(stats)
            
            logger.info(
                f"Retrieved transaction statistics for user {request.user.id}"
            )
            
            return Response(serializer.data)
        
        except Exception as e:
            logger.error(
                f"Failed to retrieve statistics for user {request.user.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': _("Failed to retrieve statistics")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def summary(self, request: Request):
        """
        Get comprehensive transaction summary
        
        Query Parameters:
            - wallet_id: Filter by specific wallet (optional)
            - start_date: Start date for summary (optional)
            - end_date: End date for summary (optional)
        
        Returns:
            Response: Transaction summary grouped by type and status
        """
        try:
            # Parse filters
            wallet_id = request.query_params.get('wallet_id')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            
            # Get wallet if specified
            wallet = None
            if wallet_id:
                wallet = get_object_or_404(
                    Wallet,
                    id=wallet_id,
                    user=request.user
                )
            
            # Get summary
            summary = self.transaction_service.get_transaction_summary(
                wallet=wallet,
                start_date=start_date,
                end_date=end_date
            )
            
            serializer = self.get_serializer(summary)
            
            logger.info(
                f"Retrieved transaction summary for user {request.user.id}"
            )
            
            return Response(serializer.data)
        
        except Exception as e:
            logger.error(
                f"Failed to retrieve summary for user {request.user.id}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': _("Failed to retrieve summary")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def export(self, request: Request):
        """
        Export transactions to CSV or Excel
        
        Query Parameters:
            - format: Export format ('csv' or 'xlsx', default: 'csv')
            - wallet_id: Filter by wallet ID (optional)
            - transaction_type: Filter by type (optional)
            - status: Filter by status (optional)
            - start_date: Start date (optional)
            - end_date: End date (optional)
        
        Returns:
            HttpResponse: File download response
        """
        try:
            # Parse parameters
            export_format = request.query_params.get('format', 'csv')
            wallet_id = request.query_params.get('wallet_id')
            transaction_type = request.query_params.get('transaction_type')
            status_param = request.query_params.get('status')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            
            # Build queryset
            queryset = self.get_queryset()
            
            if wallet_id:
                queryset = queryset.filter(wallet__id=wallet_id)
            if transaction_type:
                queryset = queryset.by_type(transaction_type)
            if status_param:
                queryset = queryset.filter(status=status_param)
            if start_date or end_date:
                queryset = queryset.in_date_range(start_date, end_date)
            
            queryset = queryset.order_by('-created_at')
            
            # Export based on format
            if export_format == 'csv':
                from wallet.utils.exporters import export_queryset_to_csv
                
                response = export_queryset_to_csv(
                    queryset=queryset,
                    fields=[
                        'id', 'reference', 'wallet.tag', 'wallet.user.email',
                        'amount.amount', 'amount.currency.code', 'fees.amount',
                        'transaction_type', 'status', 'description',
                        'created_at', 'completed_at'
                    ],
                    filename_prefix='transactions'
                )
            elif export_format == 'xlsx':
                from wallet.utils.exporters import export_queryset_to_excel
                
                response = export_queryset_to_excel(
                    queryset=queryset,
                    fields=[
                        'id', 'reference', 'wallet.tag', 'wallet.user.email',
                        'amount.amount', 'amount.currency.code', 'fees.amount',
                        'transaction_type', 'status', 'description',
                        'created_at', 'completed_at'
                    ],
                    filename_prefix='transactions'
                )
            else:
                return Response(
                    {'error': _("Invalid export format. Use 'csv' or 'xlsx'")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(
                f"Exported {queryset.count()} transactions to {export_format} "
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