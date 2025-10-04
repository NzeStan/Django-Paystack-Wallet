# from rest_framework import viewsets, status, permissions
# from rest_framework.decorators import action
# from rest_framework.response import Response
# from django.utils.translation import gettext_lazy as _

# from wallet.models import Transaction, Wallet
# from wallet.serializers.transaction_serializer import (
#     TransactionSerializer, TransactionDetailSerializer, TransactionListSerializer,
#     TransactionFilterSerializer, TransactionVerifySerializer, TransactionRefundSerializer
# )
# from wallet.services.transaction_service import TransactionService


# class IsWalletOwner(permissions.BasePermission):
#     """Permission to check if user is the wallet owner"""
    
#     def has_object_permission(self, request, view, obj):
#         return obj.wallet.user == request.user


# class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
#     """
#     API endpoint for transactions
#     """
#     serializer_class = TransactionSerializer
#     permission_classes = [permissions.IsAuthenticated, IsWalletOwner]
    
#     def get_queryset(self):
#         """Get transactions for the current user's wallets"""
#         user_wallets = Wallet.objects.filter(user=self.request.user)
#         return Transaction.objects.filter(wallet__in=user_wallets)
    
#     def get_serializer_class(self):
#         """Return the appropriate serializer based on action"""
#         if self.action == 'retrieve':
#             return TransactionDetailSerializer
#         elif self.action == 'list':
#             return TransactionListSerializer
#         elif self.action == 'verify':
#             return TransactionVerifySerializer
#         elif self.action == 'refund':
#             return TransactionRefundSerializer
        
#         return self.serializer_class
        
#     def list(self, request, *args, **kwargs):
#         """List transactions with filtering"""
#         # Parse filter parameters
#         filter_serializer = TransactionFilterSerializer(data=request.query_params)
#         filter_serializer.is_valid(raise_exception=True)
        
#         # Get filter parameters
#         wallet_id = filter_serializer.validated_data.get('wallet_id')
#         transaction_type = filter_serializer.validated_data.get('transaction_type')
#         status_param = filter_serializer.validated_data.get('status')
#         reference = filter_serializer.validated_data.get('reference')
#         start_date = filter_serializer.validated_data.get('start_date')
#         end_date = filter_serializer.validated_data.get('end_date')
#         min_amount = filter_serializer.validated_data.get('min_amount')
#         max_amount = filter_serializer.validated_data.get('max_amount')
#         payment_method = filter_serializer.validated_data.get('payment_method')
#         limit = filter_serializer.validated_data.get('limit', 20)
#         offset = filter_serializer.validated_data.get('offset', 0)
        
#         # Build queryset based on filters
#         queryset = self.get_queryset()
        
#         if wallet_id:
#             queryset = queryset.filter(wallet__id=wallet_id)
        
#         if transaction_type:
#             queryset = queryset.filter(transaction_type=transaction_type)
        
#         if status_param:
#             queryset = queryset.filter(status=status_param)
        
#         if reference:
#             queryset = queryset.filter(reference=reference)
        
#         if start_date:
#             queryset = queryset.filter(created_at__gte=start_date)
        
#         if end_date:
#             queryset = queryset.filter(created_at__lte=end_date)
        
#         if min_amount:
#             queryset = queryset.filter(amount__gte=min_amount)
        
#         if max_amount:
#             queryset = queryset.filter(amount__lte=max_amount)
        
#         if payment_method:
#             queryset = queryset.filter(payment_method=payment_method)
        
#         # Order by most recent first
#         queryset = queryset.order_by('-created_at')
        
#         # Get total count
#         total_count = queryset.count()
        
#         # Apply pagination
#         queryset = queryset[offset:offset + limit]
        
#         # Serialize data
#         serializer = self.get_serializer(queryset, many=True)
        
#         # Return with pagination info
#         return Response({
#             'count': total_count,
#             'next': offset + limit if offset + limit < total_count else None,
#             'previous': offset - limit if offset > 0 else None,
#             'results': serializer.data
#         })
    
#     @action(detail=False, methods=['post'])
#     def verify(self, request):
#         """
#         Verify a transaction by reference
#         """
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
        
#         transaction_service = TransactionService()
        
#         try:
#             # Verify transaction
#             reference = serializer.validated_data['reference']
            
#             # First check if it's a local transaction
#             try:
#                 transaction = Transaction.objects.get(reference=reference)
                
#                 # Check if user has access to this transaction
#                 if transaction.wallet.user != request.user:
#                     return Response(
#                         {"detail": _("You do not have permission to access this transaction")},
#                         status=status.HTTP_403_FORBIDDEN
#                     )
                
#                 # Return transaction details
#                 return Response(
#                     TransactionDetailSerializer(transaction).data,
#                     status=status.HTTP_200_OK
#                 )
#             except Transaction.DoesNotExist:
#                 # Not a local transaction, verify with Paystack
#                 verification_data = transaction_service.verify_paystack_transaction(reference)
#                 return Response(verification_data, status=status.HTTP_200_OK)
#         except Exception as e:
#             return Response(
#                 {"detail": str(e)},
#                 status=status.HTTP_400_BAD_REQUEST
#             )
    
#     @action(detail=False, methods=['post'])
#     def refund(self, request):
#         """
#         Create a refund for a transaction
#         """
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)

#         transaction_id = serializer.validated_data['transaction_id']
#         amount = serializer.validated_data.get('amount')
#         reason = serializer.validated_data.get('reason')

#         # ✅ Check if transaction exists
#         from wallet.models import Transaction
#         try:
#             transaction = Transaction.objects.get(id=transaction_id)
#         except Transaction.DoesNotExist:
#             return Response(
#                 {"detail": _("Transaction not found")},
#                 status=status.HTTP_404_NOT_FOUND
#             )

#         # ✅ Check if user has permission
#         if transaction.wallet.user != request.user:
#             return Response(
#                 {"detail": _("You do not have permission to access this transaction")},
#                 status=status.HTTP_403_FORBIDDEN
#             )

#         # ✅ Check if transaction is refundable
#         if transaction.status != 'success':
#             return Response(
#                 {"detail": _("Only successful transactions can be refunded")},
#                 status=status.HTTP_400_BAD_REQUEST
#             )

#         if transaction.transaction_type not in ['payment', 'deposit']:
#             return Response(
#                 {"detail": _("Only payment and deposit transactions can be refunded")},
#                 status=status.HTTP_400_BAD_REQUEST
#             )

#         if amount and amount > transaction.amount.amount:
#             return Response(
#                 {"detail": _("Refund amount cannot exceed original transaction amount")},
#                 status=status.HTTP_400_BAD_REQUEST
#             )

#         # ✅ Attempt refund
#         try:
#             from wallet.services.transaction_service import TransactionService
#             refund_transaction = TransactionService().refund_transaction(
#                 transaction=transaction,
#                 amount=amount,
#                 reason=reason
#             )
#             from wallet.serializers import TransactionDetailSerializer
#             return Response(
#                 TransactionDetailSerializer(refund_transaction).data,
#                 status=status.HTTP_200_OK
#             )
#         except Exception as e:
#             return Response(
#                 {"detail": str(e)},
#                 status=status.HTTP_400_BAD_REQUEST
#             )

# from rest_framework import viewsets, status, permissions
# from rest_framework.decorators import action
# from rest_framework.response import Response
# from django.utils.translation import gettext_lazy as _

# from wallet.models import Transaction, Wallet
# from wallet.serializers.transaction_serializer import (
#     TransactionSerializer, TransactionDetailSerializer, TransactionListSerializer,
#     TransactionFilterSerializer, TransactionVerifySerializer, TransactionRefundSerializer
# )
# from wallet.services.transaction_service import TransactionService


# class IsWalletOwner(permissions.BasePermission):
#     """Permission to check if user is the wallet owner"""
    
#     def has_object_permission(self, request, view, obj):
#         return obj.wallet.user == request.user


# class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
#     """
#     API endpoint for transactions
#     """
#     serializer_class = TransactionSerializer
#     permission_classes = [permissions.IsAuthenticated, IsWalletOwner]
    
#     def get_queryset(self):
#         """Get transactions for the current user's wallets"""
#         user_wallets = Wallet.objects.filter(user=self.request.user)
#         return Transaction.objects.filter(wallet__in=user_wallets)
    
#     def get_serializer_class(self):
#         """Return the appropriate serializer based on action"""
#         if self.action == 'retrieve':
#             return TransactionDetailSerializer
#         elif self.action == 'list':
#             return TransactionListSerializer
#         elif self.action == 'verify':
#             return TransactionVerifySerializer
#         elif self.action == 'refund':
#             return TransactionRefundSerializer
        
#         return self.serializer_class
        
#     def list(self, request, *args, **kwargs):
#         """List transactions with filtering"""
#         # Parse filter parameters
#         filter_serializer = TransactionFilterSerializer(data=request.query_params)
#         filter_serializer.is_valid(raise_exception=True)
        
#         # Get filter parameters
#         wallet_id = filter_serializer.validated_data.get('wallet_id')
#         transaction_type = filter_serializer.validated_data.get('transaction_type')
#         status_param = filter_serializer.validated_data.get('status')
#         reference = filter_serializer.validated_data.get('reference')
#         start_date = filter_serializer.validated_data.get('start_date')
#         end_date = filter_serializer.validated_data.get('end_date')
#         min_amount = filter_serializer.validated_data.get('min_amount')
#         max_amount = filter_serializer.validated_data.get('max_amount')
#         payment_method = filter_serializer.validated_data.get('payment_method')
#         limit = filter_serializer.validated_data.get('limit', 20)
#         offset = filter_serializer.validated_data.get('offset', 0)
        
#         # Build queryset based on filters
#         queryset = self.get_queryset()
        
#         if wallet_id:
#             queryset = queryset.filter(wallet__id=wallet_id)
        
#         if transaction_type:
#             queryset = queryset.filter(transaction_type=transaction_type)
        
#         if status_param:
#             queryset = queryset.filter(status=status_param)
        
#         if reference:
#             queryset = queryset.filter(reference=reference)
        
#         if start_date:
#             queryset = queryset.filter(created_at__gte=start_date)
        
#         if end_date:
#             queryset = queryset.filter(created_at__lte=end_date)
        
#         if min_amount:
#             queryset = queryset.filter(amount__gte=min_amount)
        
#         if max_amount:
#             queryset = queryset.filter(amount__lte=max_amount)
        
#         if payment_method:
#             queryset = queryset.filter(payment_method=payment_method)
        
#         # Order by most recent first
#         queryset = queryset.order_by('-created_at')
        
#         # Get total count
#         total_count = queryset.count()
        
#         # Apply pagination
#         queryset = queryset[offset:offset + limit]
        
#         # Serialize data
#         serializer = self.get_serializer(queryset, many=True)
        
#         # Return with pagination info
#         return Response({
#             'count': total_count,
#             'next': offset + limit if offset + limit < total_count else None,
#             'previous': offset - limit if offset > 0 else None,
#             'results': serializer.data
#         })
    
#     @action(detail=False, methods=['post'])
#     def verify(self, request):
#         """
#         Verify a transaction by reference
#         """
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
        
#         transaction_service = TransactionService()
        
#         try:
#             # Verify transaction
#             reference = serializer.validated_data['reference']
            
#             # First check if it's a local transaction
#             try:
#                 transaction = Transaction.objects.get(reference=reference)
                
#                 # Check if user has access to this transaction
#                 if transaction.wallet.user != request.user:
#                     return Response(
#                         {"detail": _("You do not have permission to access this transaction")},
#                         status=status.HTTP_403_FORBIDDEN
#                     )
                
#                 # Return transaction details
#                 return Response(
#                     TransactionDetailSerializer(transaction).data,
#                     status=status.HTTP_200_OK
#                 )
#             except Transaction.DoesNotExist:
#                 # Not a local transaction, verify with Paystack
#                 verification_data = transaction_service.verify_paystack_transaction(reference)
#                 return Response(verification_data, status=status.HTTP_200_OK)
#         except Exception as e:
#             return Response(
#                 {"detail": str(e)},
#                 status=status.HTTP_400_BAD_REQUEST
#             )
    
#     @action(detail=False, methods=['post'])
#     def refund(self, request):
#         """
#         Create a refund for a transaction
#         """
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
        
#         transaction_service = TransactionService()
        
#         try:
#             # Get transaction
#             transaction_id = serializer.validated_data['transaction_id']
#             transaction = Transaction.objects.get(id=transaction_id)
            
#             # Check if user has access to this transaction
#             if transaction.wallet.user != request.user:
#                 return Response(
#                     {"detail": _("You do not have permission to access this transaction")},
#                     status=status.HTTP_403_FORBIDDEN
#                 )
            
#             # Create refund
#             amount = serializer.validated_data.get('amount')
#             reason = serializer.validated_data.get('reason')
            
#             refund_transaction = transaction_service.refund_transaction(
#                 transaction=transaction,
#                 amount=amount,
#                 reason=reason
#             )
            
#             # Return refund transaction details
#             return Response(
#                 TransactionDetailSerializer(refund_transaction).data,
#                 status=status.HTTP_200_OK
#             )
#         except Exception as e:
#             return Response(
#                 {"detail": str(e)},
#                 status=status.HTTP_400_BAD_REQUEST
#             )
        
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _

from wallet.models import Transaction, Wallet
from wallet.serializers.transaction_serializer import (
    TransactionSerializer, TransactionDetailSerializer, TransactionListSerializer,
    TransactionFilterSerializer, TransactionVerifySerializer, TransactionRefundSerializer
)
from wallet.services.transaction_service import TransactionService


class IsWalletOwner(permissions.BasePermission):
    """Permission to check if user is the wallet owner"""
    
    def has_object_permission(self, request, view, obj):
        return obj.wallet.user == request.user


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for transactions
    """
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated, IsWalletOwner]
    
    def get_queryset(self):
        """Get transactions for the current user's wallets"""
        user_wallets = Wallet.objects.filter(user=self.request.user)
        return Transaction.objects.filter(wallet__in=user_wallets)
    
    def get_serializer_class(self):
        """Return the appropriate serializer based on action"""
        if self.action == 'retrieve':
            return TransactionDetailSerializer
        elif self.action == 'list':
            return TransactionListSerializer
        elif self.action == 'verify':
            return TransactionVerifySerializer
        elif self.action == 'refund':
            return TransactionRefundSerializer
        
        return self.serializer_class
        
    def list(self, request, *args, **kwargs):
        """List transactions with filtering"""
        # Parse filter parameters
        filter_serializer = TransactionFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        
        # Get filter parameters
        wallet_id = filter_serializer.validated_data.get('wallet_id')
        transaction_type = filter_serializer.validated_data.get('transaction_type')
        status_param = filter_serializer.validated_data.get('status')
        reference = filter_serializer.validated_data.get('reference')
        start_date = filter_serializer.validated_data.get('start_date')
        end_date = filter_serializer.validated_data.get('end_date')
        min_amount = filter_serializer.validated_data.get('min_amount')
        max_amount = filter_serializer.validated_data.get('max_amount')
        payment_method = filter_serializer.validated_data.get('payment_method')
        limit = filter_serializer.validated_data.get('limit', 20)
        offset = filter_serializer.validated_data.get('offset', 0)
        
        # Build queryset based on filters
        queryset = self.get_queryset()
        
        if wallet_id:
            queryset = queryset.filter(wallet__id=wallet_id)
        
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        if reference:
            queryset = queryset.filter(reference=reference)
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        if min_amount:
            queryset = queryset.filter(amount__gte=min_amount)
        
        if max_amount:
            queryset = queryset.filter(amount__lte=max_amount)
        
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)
        
        # Order by most recent first
        queryset = queryset.order_by('-created_at')
        
        # Get total count
        total_count = queryset.count()
        
        # Apply pagination
        queryset = queryset[offset:offset + limit]
        
        # Serialize data
        serializer = self.get_serializer(queryset, many=True)
        
        # Return with pagination info
        return Response({
            'count': total_count,
            'next': offset + limit if offset + limit < total_count else None,
            'previous': offset - limit if offset > 0 else None,
            'results': serializer.data
        })
    
    @action(detail=False, methods=['post'])
    def verify(self, request):
        """
        Verify a transaction by reference
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        transaction_service = TransactionService()
        
        try:
            # Verify transaction
            reference = serializer.validated_data['reference']
            
            # First check if it's a local transaction
            try:
                transaction = Transaction.objects.get(reference=reference)
                
                # Check if user has access to this transaction
                if transaction.wallet.user != request.user:
                    return Response(
                        {"detail": _("You do not have permission to access this transaction")},
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Return transaction details
                return Response(
                    TransactionDetailSerializer(transaction).data,
                    status=status.HTTP_200_OK
                )
            except Transaction.DoesNotExist:
                # Not a local transaction, verify with Paystack
                verification_data = transaction_service.verify_paystack_transaction(reference)
                return Response(verification_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def refund(self, request):
        """
        Create a refund for a transaction
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        transaction_service = TransactionService()
        
        try:
            # Get transaction
            transaction_id = serializer.validated_data['transaction_id']
            transaction = Transaction.objects.get(id=transaction_id)
            
            # Check if user has access to this transaction
            if transaction.wallet.user != request.user:
                return Response(
                    {"detail": _("You do not have permission to access this transaction")},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Create refund
            amount = serializer.validated_data.get('amount')
            reason = serializer.validated_data.get('reason')
            
            refund_transaction = transaction_service.refund_transaction(
                transaction=transaction,
                amount=amount,
                reason=reason
            )
            
            # Return refund transaction details
            return Response(
                TransactionDetailSerializer(refund_transaction).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )