"""
Django Paystack Wallet - Wallet API Views
Refactored with query optimization, comprehensive error handling, and clean architecture
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
from wallet.models import Wallet, Transaction, BankAccount
from decimal import Decimal

from wallet.serializers.wallet_serializer import (
    WalletSerializer,
    WalletDetailSerializer,
    WalletCreateUpdateSerializer,
    WalletDepositSerializer,
    WalletWithdrawSerializer,
    WalletTransferSerializer,
    FinalizeWithdrawalSerializer
)
from wallet.serializers.transaction_serializer import TransactionListSerializer
from wallet.services.wallet_service import WalletService
from wallet.services.transaction_service import TransactionService
from wallet.utils.id_generators import generate_transaction_reference
from wallet.exceptions import (
    WalletLocked,
    InsufficientFunds,
    BankAccountError,
    PaystackAPIError
)
from wallet.constants import (
       TRANSACTION_TYPE_WITHDRAWAL,
       TRANSACTION_STATUS_PENDING,
       TRANSACTION_STATUS_SUCCESS,
      TRANSACTION_STATUS_FAILED,
      TRANSACTION_TYPE_DEPOSIT

  )


logger = logging.getLogger(__name__)


# ==========================================
# CUSTOM PERMISSIONS
# ==========================================

class IsWalletOwner(permissions.BasePermission):
    """
    Permission to check if user is the wallet owner
    
    Ensures that users can only access and modify their own wallets.
    """
    
    message = _("You do not have permission to access this wallet")
    
    def has_object_permission(self, request: Request, view: Any, obj: Wallet) -> bool:
        """
        Check if user owns the wallet
        
        Args:
            request (Request): HTTP request
            view: View instance
            obj (Wallet): Wallet object to check
            
        Returns:
            bool: True if user owns wallet
        """
        return obj.user == request.user


# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def get_client_ip(request: Request) -> str:
    """Get client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def build_error_response(message: str, status_code: int) -> Response:
    """Build standardized error response"""
    return Response(
        {'detail': str(message)},
        status=status_code
    )


# ==========================================
# WALLET VIEWSET
# ==========================================

class WalletViewSet(viewsets.ModelViewSet):
    """
    API endpoint for wallet operations
    
    Provides CRUD operations for wallets plus custom actions for
    deposits, withdrawals, transfers, and account management.
    
    List/Retrieve: GET /api/wallets/
    Create: POST /api/wallets/
    Update: PUT/PATCH /api/wallets/{id}/
    Delete: DELETE /api/wallets/{id}/
    
    Custom Actions:
    - deposit: POST /api/wallets/{id}/deposit/
    - withdraw: POST /api/wallets/{id}/withdraw/
    - transfer: POST /api/wallets/{id}/transfer/
    - balance: GET /api/wallets/{id}/balance/
    - transactions: GET /api/wallets/{id}/transactions/
    - dedicated_account: GET /api/wallets/{id}/dedicated_account/
    """
    
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated, IsWalletOwner]
    
    def get_queryset(self):
        """
        Get wallets for the current user with optimized queries
        
        Returns:
            QuerySet: Filtered and optimized wallet queryset
        """
        return Wallet.objects.filter(user=self.request.user).select_related('user')
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action
        
        Returns:
            Serializer class: Appropriate serializer for the action
        """
        action_serializers = {
            'retrieve': WalletDetailSerializer,
            'create': WalletCreateUpdateSerializer,
            'update': WalletCreateUpdateSerializer,
            'partial_update': WalletCreateUpdateSerializer,
            'deposit': WalletDepositSerializer,
            'withdraw': WalletWithdrawSerializer,
            'transfer': WalletTransferSerializer,
            'finalize_withdrawal': FinalizeWithdrawalSerializer,  # <-- Added
        }

        return action_serializers.get(self.action, self.serializer_class)

    
    def get_object(self):
        """
        Get wallet object with special handling for 'default' pk
        
        Returns:
            Wallet: Wallet instance
        """
        pk = self.kwargs.get('pk')
        
        # Handle 'default' as special keyword for user's wallet
        if pk == 'default':
            try:
                wallet = Wallet.objects.select_related('user').get(user=self.request.user)
                self.check_object_permissions(self.request, wallet)
                return wallet
            except Wallet.DoesNotExist:
                # Create wallet if it doesn't exist
                wallet_service = WalletService()
                wallet = wallet_service.get_wallet(self.request.user)
                self.check_object_permissions(self.request, wallet)
                return wallet
        
        # Standard object retrieval
        return super().get_object()
    
    # ==========================================
    # CRUD OPERATIONS
    # ==========================================
    
    def create(self, request: Request, *args, **kwargs) -> Response:
        """
        Create a new wallet for the user
        
        Args:
            request (Request): HTTP request
            
        Returns:
            Response: Created wallet data
        """
        # Check if user already has a wallet
        if Wallet.objects.filter(user=request.user).exists():
            logger.warning(f"User {request.user.id} attempted to create duplicate wallet")
            return build_error_response(
                _("User already has a wallet"),
                status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Create wallet using service
            wallet_service = WalletService()
            wallet = wallet_service.get_wallet(request.user)
            
            # Update wallet with provided data
            serializer = self.get_serializer(wallet, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            
            logger.info(f"Created wallet {wallet.id} for user {request.user.id}")
            
            # Return detailed wallet info
            return Response(
                WalletDetailSerializer(wallet).data,
                status=status.HTTP_201_CREATED
            )
        
        except Exception as e:
            logger.error(
                f"Error creating wallet for user {request.user.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Failed to create wallet. Please try again."),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # DEPOSIT ACTION
    # ==========================================
    
    @action(detail=True, methods=['post'])
    def deposit(self, request: Request, pk=None) -> Response:
        """
        Initialize a deposit to the wallet
        
        This creates a Transaction record with PENDING status and a Paystack charge 
        transaction, then returns the authorization URL for completing the payment.
        
        The Transaction record is created BEFORE initializing with Paystack so that
        when the webhook arrives, it can find and update the transaction.
        
        POST /api/wallets/{id}/deposit/
        
        Request Body:
        {
            "amount": 1000.00,
            "email": "user@example.com",  # Optional
            "callback_url": "https://...",  # Optional
            "description": "Wallet top-up",  # Optional
            "reference": "REF123",  # Optional
            "metadata": {}  # Optional
        }
        
        Args:
            request (Request): HTTP request
            pk: Wallet primary key
            
        Returns:
            Response: Charge initialization data with authorization URL and transaction details
        """
        wallet = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        transaction_service = TransactionService()
        
        try:
            # Extract validated data
            amount = serializer.validated_data['amount']
            email = serializer.validated_data.get('email') or request.user.email
            callback_url = serializer.validated_data.get('callback_url', '')
            reference = serializer.validated_data.get('reference') or generate_transaction_reference()
            description = serializer.validated_data.get('description', 'Card deposit to wallet')
            
            # Prepare metadata
            metadata = serializer.validated_data.get('metadata') or {}
            if not isinstance(metadata, dict):
                metadata = {}
            else:
                metadata = metadata.copy()
            
            # Add request context to metadata
            metadata.update({
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'description': description,
            })
            
            logger.info(
                f"Initializing deposit for wallet {wallet.id}: "
                f"amount={amount}, reference={reference}"
            )
            
            # CRITICAL: Create Transaction record FIRST with PENDING status
            # This ensures the webhook can find and update the transaction
            with db_transaction.atomic():
                transaction = transaction_service.create_transaction(
                    wallet=wallet,
                    amount=amount,
                    transaction_type=TRANSACTION_TYPE_DEPOSIT,
                    status=TRANSACTION_STATUS_PENDING,
                    reference=reference,
                    description=description,
                    metadata=metadata
                )
                
                logger.info(
                    f"Created pending deposit transaction {transaction.id} for wallet {wallet.id}: "
                    f"reference={reference}"
                )
                
                # Initialize Paystack transaction
                charge_data = wallet_service.initialize_card_charge(
                    wallet=wallet,
                    amount=amount,
                    email=email,
                    reference=reference,
                    callback_url=callback_url,
                    metadata=metadata
                )
                
                # Add transaction ID to response
                charge_data['transaction_id'] = str(transaction.id)
                charge_data['transaction_reference'] = reference
                
                logger.info(
                    f"Deposit initialized for wallet {wallet.id}: "
                    f"reference={reference}, access_code={charge_data.get('access_code')}, "
                    f"transaction_id={transaction.id}"
                )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        
        except PaystackAPIError as e:
            logger.error(
                f"Paystack API error during deposit initialization for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            
            # If we created a transaction, mark it as failed
            try:
                if 'transaction' in locals():
                    transaction_service.mark_as_failed(
                        transaction,
                        reason=f"Paystack API error: {str(e)}"
                    )
            except Exception as inner_e:
                logger.error(f"Failed to mark transaction as failed: {str(inner_e)}")
            
            return build_error_response(
                _("Payment gateway error. Please try again."),
                status.HTTP_502_BAD_GATEWAY
            )
        
        except Exception as e:
            logger.error(
                f"Error initializing deposit for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            
            # If we created a transaction, mark it as failed
            try:
                if 'transaction' in locals():
                    transaction_service.mark_as_failed(
                        transaction,
                        reason=f"Initialization error: {str(e)}"
                    )
            except Exception as inner_e:
                logger.error(f"Failed to mark transaction as failed: {str(inner_e)}")
            
            return build_error_response(
                _("Failed to initialize deposit. Please try again."),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # WITHDRAWAL ACTION
    # ==========================================
    
    @action(detail=True, methods=['post'])
    def withdraw(self, request: Request, pk=None) -> Response:
        """
        Withdraw funds from wallet to a bank account
        
        POST /api/wallets/{id}/withdraw/
        
        Request Body:
        {
            "amount": 5000.00,
            "bank_account_id": "uuid-here",
            "description": "Withdrawal",  # Optional
            "reference": "REF123",  # Optional
            "metadata": {}  # Optional
        }
        
        Response Success (200):
        {
            "status": "success",
            "message": "Withdrawal initiated successfully",
            "transaction": {...},
            "transfer": {
                "transfer_code": "TRF_xxxxx",
                "status": "pending|otp|success",
                "requires_otp": false
            }
        }
        
        Response OTP Required (200):
        {
            "status": "pending_otp",
            "message": "OTP required to complete withdrawal",
            "transaction": {...},
            "transfer": {
                "transfer_code": "TRF_xxxxx",
                "status": "otp",
                "requires_otp": true
            }
        }
        """
        wallet = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        
        try:
            # Extract validated data
            amount = serializer.validated_data['amount']
            bank_account_id = serializer.validated_data['bank_account_id']
            description = serializer.validated_data.get(
                'description', 
                'Withdrawal to bank account'
            )
            reference = serializer.validated_data.get('reference')
            metadata = serializer.validated_data.get('metadata') or {}
            
            # Add request context to metadata
            if isinstance(metadata, dict):
                metadata = metadata.copy()
                metadata.update({
                    'ip_address': get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                })
            
            logger.info(
                f"Initiating withdrawal for wallet {wallet.id}: "
                f"amount={amount}, bank_account={bank_account_id}"
            )
            
            # Get and validate bank account
            try:
                bank_account = BankAccount.objects.select_related('bank').get(
                    id=bank_account_id,
                    wallet=wallet,
                    is_active=True
                )
            except BankAccount.DoesNotExist:
                logger.warning(
                    f"Bank account {bank_account_id} not found or inactive for wallet {wallet.id}"
                )
                return build_error_response(
                    _("Bank account not found or inactive"),
                    status.HTTP_404_NOT_FOUND
                )
            
            # Validate bank account has recipient code
            if not bank_account.paystack_recipient_code:
                logger.warning(
                    f"Bank account {bank_account.id} missing recipient code"
                )
                return build_error_response(
                    _("Bank account is not properly configured for withdrawals"),
                    status.HTTP_400_BAD_REQUEST
                )
            
            # Convert amount to Decimal if it's not already
            if not isinstance(amount, Decimal):
                amount = Decimal(str(amount))
            
            # Validate amount is positive
            if amount <= 0:
                logger.warning(
                    f"Invalid withdrawal amount {amount} for wallet {wallet.id}"
                )
                return build_error_response(
                    _("Amount must be greater than zero"),
                    status.HTTP_400_BAD_REQUEST
                )
            
            # Process withdrawal
            transaction, transfer_data = wallet_service.withdraw_to_bank(
                wallet=wallet,
                amount=amount,
                bank_account=bank_account,
                reason=description,
                metadata=metadata,
                reference=reference
            )
            
            logger.info(
                f"Withdrawal initiated for wallet {wallet.id}: "
                f"transaction={transaction.id}, "
                f"transfer_code={transfer_data.get('transfer_code')}, "
                f"status={transfer_data.get('status')}"
            )
            
            # Prepare response
            from wallet.serializers.transaction_serializer import TransactionSerializer
            
            # Check if OTP is required
            requires_otp = transfer_data.get('requires_otp', False)
            transfer_status = transfer_data.get('status', 'pending')
            
            response_data = {
                'transaction': TransactionSerializer(transaction).data,
                'transfer': {
                    'transfer_code': transfer_data.get('transfer_code'),
                    'status': transfer_status,
                    'requires_otp': requires_otp,
                }
            }
            
            if requires_otp:
                response_data['status'] = 'pending_otp'
                response_data['message'] = _(
                    'OTP required to complete withdrawal. '
                    'Please check your phone for OTP and call finalize_withdrawal endpoint.'
                )
            else:
                response_data['status'] = 'success'
                response_data['message'] = _('Withdrawal initiated successfully')
            
            return Response(response_data, status=status.HTTP_200_OK)
        
        except BankAccountError as e:
            logger.warning(
                f"Bank account error during withdrawal for wallet {wallet.id}: {str(e)}"
            )
            return build_error_response(str(e), status.HTTP_400_BAD_REQUEST)
        
        except InsufficientFunds as e:
            logger.warning(
                f"Insufficient funds for withdrawal from wallet {wallet.id}: {str(e)}"
            )
            return build_error_response(str(e), status.HTTP_400_BAD_REQUEST)
        
        except WalletLocked as e:
            logger.warning(
                f"Wallet {wallet.id} is locked, withdrawal denied"
            )
            return build_error_response(str(e), status.HTTP_403_FORBIDDEN)
        
        except PaystackAPIError as e:
            logger.error(
                f"Paystack API error during withdrawal for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Payment gateway error. Please try again later."),
                status.HTTP_502_BAD_GATEWAY
            )
        
        except ValueError as e:
            logger.warning(
                f"Validation error during withdrawal for wallet {wallet.id}: {str(e)}"
            )
            return build_error_response(str(e), status.HTTP_400_BAD_REQUEST)
        
        except Exception as e:
            logger.error(
                f"Unexpected error processing withdrawal for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Failed to process withdrawal. Please try again later."),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='finalize-withdrawal')
    def finalize_withdrawal(self, request: Request, pk=None) -> Response:
        """
        Finalize a pending bank withdrawal with OTP
        
        This endpoint is used when a withdrawal requires OTP verification.
        After calling the withdraw endpoint, if the response indicates OTP
        is required, the user receives an OTP and calls this endpoint to
        complete the withdrawal.
        
        POST /api/wallets/{id}/finalize-withdrawal/
        
        Request Body:
        {
            "transfer_code": "TRF_xxxxx",  # From initial withdrawal response
            "otp": "123456"  # OTP received by user
        }
        
        Response Success (200):
        {
            "status": "success",
            "message": "Transfer completed successfully",
            "transaction": {...}
        }
        
        Response Failed (400):
        {
            "status": "failed",
            "message": "Transfer finalization failed",
            "transaction": {...}
        }
        
        Response Processing (202):
        {
            "status": "processing",
            "message": "Transfer is being processed",
            "transaction": {...}
        }
        """
        wallet = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        
        try:
            # Extract validated data
            transfer_code = serializer.validated_data['transfer_code']
            otp = serializer.validated_data['otp']
            
            logger.info(
                f"Finalizing withdrawal for wallet {wallet.id}: "
                f"transfer_code={transfer_code}"
            )
            
            # Find the transaction by transfer code
            try:
                transaction = Transaction.objects.select_related('wallet').get(
                    wallet=wallet,
                    paystack_reference=transfer_code,
                    transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
                    status=TRANSACTION_STATUS_PENDING
                )
            except Transaction.DoesNotExist:
                logger.warning(
                    f"No pending withdrawal transaction found for wallet {wallet.id} "
                    f"with transfer_code={transfer_code}"
                )
                return build_error_response(
                    _("No pending withdrawal found with this transfer code"),
                    status.HTTP_404_NOT_FOUND
                )
            except Transaction.MultipleObjectsReturned:
                logger.error(
                    f"Multiple pending withdrawal transactions found for wallet {wallet.id} "
                    f"with transfer_code={transfer_code}"
                )
                return build_error_response(
                    _("Multiple pending withdrawals found. Please contact support."),
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Finalize the withdrawal
            finalization_response = wallet_service.finalize_withdrawal(
                transaction=transaction,
                otp=otp
            )
            
            # Refresh transaction from database to get updated status
            transaction.refresh_from_db()
            
            logger.info(
                f"Withdrawal finalized for wallet {wallet.id}: "
                f"transaction={transaction.id}, "
                f"status={transaction.status}, "
                f"paystack_status={finalization_response.get('status')}"
            )
            
            # Serialize the updated transaction
            from wallet.serializers.transaction_serializer import TransactionDetailSerializer
            transaction_serializer = TransactionDetailSerializer(
                transaction,
                context={'request': request}
            )
            
            # Prepare response based on finalization status
            response_status = finalization_response.get('status', '').lower()
            
            if response_status == 'success' or transaction.status == TRANSACTION_STATUS_SUCCESS:
                response_data = {
                    'status': 'success',
                    'message': _('Transfer completed successfully'),
                    'transaction': transaction_serializer.data
                }
                return Response(response_data, status=status.HTTP_200_OK)
            
            elif response_status in ['failed', 'error'] or transaction.status == TRANSACTION_STATUS_FAILED:
                response_data = {
                    'status': 'failed',
                    'message': finalization_response.get(
                        'message', 
                        _('Transfer finalization failed')
                    ),
                    'transaction': transaction_serializer.data
                }
                return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
            
            else:
                # Still processing
                response_data = {
                    'status': 'processing',
                    'message': _('Transfer is being processed'),
                    'transaction': transaction_serializer.data
                }
                return Response(response_data, status=status.HTTP_202_ACCEPTED)
        
        except PaystackAPIError as e:
            logger.error(
                f"Paystack API error during withdrawal finalization for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Payment gateway error. Please try again or contact support."),
                status.HTTP_502_BAD_GATEWAY
            )
        
        except ValueError as e:
            logger.warning(
                f"Validation error during withdrawal finalization for wallet {wallet.id}: {str(e)}"
            )
            return build_error_response(
                str(e),
                status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(
                f"Unexpected error finalizing withdrawal for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Failed to finalize withdrawal. Please try again later."),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ==========================================
    # TRANSFER ACTION
    # ==========================================
    
    @action(detail=True, methods=['post'])
    def transfer(self, request: Request, pk=None) -> Response:
        """
        Transfer funds to another wallet
        
        POST /api/wallets/{id}/transfer/
        
        Request Body:
        {
            "amount": 1000.00,
            "destination_wallet_id": "uuid-here",
            "description": "Payment",  # Optional
            "reference": "REF123",  # Optional
            "metadata": {}  # Optional
        }
        
        Args:
            request (Request): HTTP request
            pk: Wallet primary key
            
        Returns:
            Response: Transaction data
        """
        source_wallet = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Extract validated data
            amount = serializer.validated_data['amount']
            destination_wallet_id = serializer.validated_data['destination_wallet_id']
            description = serializer.validated_data.get('description', 'Wallet transfer')
            reference = serializer.validated_data.get('reference')
            metadata = serializer.validated_data.get('metadata') or {}
            
            # Validate amount
            if amount <= 0:
                logger.warning(
                    f"Invalid transfer amount {amount} for wallet {source_wallet.id}"
                )
                return build_error_response(
                    _("Transfer amount must be greater than zero"),
                    status.HTTP_400_BAD_REQUEST
                )
            
            # Check for self-transfer
            if str(destination_wallet_id) == str(source_wallet.id):
                logger.warning(
                    f"Self-transfer attempted for wallet {source_wallet.id}"
                )
                return build_error_response(
                    _("Cannot transfer to the same wallet"),
                    status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(
                f"Initiating transfer from wallet {source_wallet.id}: "
                f"amount={amount}, destination={destination_wallet_id}"
            )
            
            # Get destination wallet
            destination_wallet = get_object_or_404(
                Wallet.objects.select_related('user'),
                id=destination_wallet_id,
                is_active=True
            )
            
            # Add request context to metadata
            if isinstance(metadata, dict):
                metadata = metadata.copy()
                metadata.update({
                    'ip_address': get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                })
            
            # Process transfer using transaction service
            transaction_service = TransactionService()
            transaction = transaction_service.transfer_between_wallets(
                source_wallet=source_wallet,
                destination_wallet=destination_wallet,
                amount=amount,
                description=description,
                metadata=metadata,
                reference=reference
            )
            
            logger.info(
                f"Transfer completed: transaction={transaction.id}, "
                f"from={source_wallet.id}, to={destination_wallet.id}"
            )
            
            # Return transaction data
            from wallet.serializers.transaction_serializer import TransactionSerializer
            return Response(
                TransactionSerializer(transaction).data,
                status=status.HTTP_200_OK
            )
        
        except InsufficientFunds as e:
            logger.warning(
                f"Insufficient funds for transfer from wallet {source_wallet.id}: {str(e)}"
            )
            return build_error_response(str(e), status.HTTP_400_BAD_REQUEST)
        
        except WalletLocked as e:
            logger.warning(
                f"Wallet locked during transfer attempt: {str(e)}"
            )
            return build_error_response(str(e), status.HTTP_403_FORBIDDEN)
        
        except Wallet.DoesNotExist:
            logger.warning(
                f"Invalid destination wallet for transfer from {source_wallet.id}"
            )
            return build_error_response(
                _("Invalid or inactive destination wallet"),
                status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(
                f"Error processing transfer from wallet {source_wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Failed to process transfer. Please try again."),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # BALANCE ACTION
    # ==========================================
    
    @action(detail=True, methods=['get'])
    def balance(self, request: Request, pk=None) -> Response:
        """
        Get current wallet balance
        
        GET /api/wallets/{id}/balance/
        
        Args:
            request (Request): HTTP request
            pk: Wallet primary key
            
        Returns:
            Response: Balance information
        """
        wallet = self.get_object()
        wallet_service = WalletService()
        
        try:
            # Get current balance
            balance = wallet_service.get_balance(wallet)
            
            logger.debug(f"Balance retrieved for wallet {wallet.id}: {balance}")
            
            response_data = {
                'balance_amount': balance.amount,
                'balance_currency': balance.currency.code,
                'available_balance': balance.amount,
                'is_operational': wallet.is_operational,
                'last_updated': wallet.updated_at,
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(
                f"Error retrieving balance for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Failed to retrieve balance"),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # TRANSACTIONS ACTION
    # ==========================================
    
    @action(detail=True, methods=['get'])
    def transactions(self, request: Request, pk=None) -> Response:
        """
        Get wallet transaction history
        
        GET /api/wallets/{id}/transactions/?limit=20&offset=0
        
        Query Parameters:
        - limit: Number of transactions to return (default: 20)
        - offset: Offset for pagination (default: 0)
        
        Args:
            request (Request): HTTP request
            pk: Wallet primary key
            
        Returns:
            Response: Paginated transaction list
        """
        wallet = self.get_object()
        
        try:
            # Get pagination parameters
            limit = int(request.query_params.get('limit', 20))
            offset = int(request.query_params.get('offset', 0))
            
            # Validate pagination parameters
            limit = min(max(1, limit), 100)  # Between 1 and 100
            offset = max(0, offset)  # Non-negative
            
            logger.debug(
                f"Fetching transactions for wallet {wallet.id}: "
                f"limit={limit}, offset={offset}"
            )
            
            # Get transactions with optimized query
            transactions = Transaction.objects.filter(
                wallet=wallet
            ).select_related(
                'recipient_wallet__user',
                'recipient_bank_account__bank',
                'card'
            ).order_by('-created_at')[offset:offset + limit]
            
            # Get total count
            total_count = Transaction.objects.filter(wallet=wallet).count()
            
            # Serialize transactions
            transaction_data = TransactionListSerializer(transactions, many=True).data
            
            # Prepare pagination info
            next_offset = offset + limit if offset + limit < total_count else None
            previous_offset = offset - limit if offset > 0 else None
            
            response_data = {
                'count': total_count,
                'next': next_offset,
                'previous': previous_offset,
                'results': transaction_data
            }
            
            logger.info(
                f"Retrieved {len(transaction_data)} transactions for wallet {wallet.id}"
            )
            
            return Response(response_data, status=status.HTTP_200_OK)
        
        except ValueError as e:
            logger.warning(
                f"Invalid pagination parameters for wallet {wallet.id}: {str(e)}"
            )
            return build_error_response(
                _("Invalid pagination parameters"),
                status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(
                f"Error fetching transactions for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("Failed to retrieve transactions"),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ==========================================
    # DEDICATED ACCOUNT ACTION
    # ==========================================
    
    @action(detail=True, methods=['get'])
    def dedicated_account(self, request: Request, pk=None) -> Response:
        """
        Get or create dedicated virtual account
        
        GET /api/wallets/{id}/dedicated_account/
        
        Args:
            request (Request): HTTP request
            pk: Wallet primary key
            
        Returns:
            Response: Dedicated account details
        """
        wallet = self.get_object()
        wallet_service = WalletService()
        
        try:
            logger.info(f"Dedicated account requested for wallet {wallet.id}")
            
            # Check if wallet already has a dedicated account
            if wallet.dedicated_account_number:
                logger.info(
                    f"Existing dedicated account found for wallet {wallet.id}: "
                    f"{wallet.dedicated_account_number}"
                )
                
                # Get account name
                if hasattr(wallet.user, 'get_full_name'):
                    account_name = wallet.user.get_full_name()
                else:
                    account_name = str(wallet.user)
                
                response_data = {
                    'account_number': wallet.dedicated_account_number,
                    'bank_name': wallet.dedicated_account_bank or 'N/A',
                    'account_name': account_name
                }
                
                return Response(response_data, status=status.HTTP_200_OK)
            
            # Create dedicated account
            logger.info(f"Creating new dedicated account for wallet {wallet.id}")
            
            success = wallet_service.create_dedicated_account(wallet)
            
            if success:
                logger.info(
                    f"Dedicated account created successfully for wallet {wallet.id}"
                )
                
                # Refresh wallet to get updated account details
                wallet.refresh_from_db()
                
                # Get account name
                if hasattr(wallet.user, 'get_full_name'):
                    account_name = wallet.user.get_full_name()
                else:
                    account_name = str(wallet.user)
                
                response_data = {
                    'account_number': wallet.dedicated_account_number,
                    'bank_name': wallet.dedicated_account_bank or 'N/A',
                    'account_name': account_name
                }
                
                return Response(response_data, status=status.HTTP_201_CREATED)
            
            # Failed to create account
            logger.error(f"Failed to create dedicated account for wallet {wallet.id}")
            return build_error_response(
                _("Failed to create dedicated account. Please try again later."),
                status.HTTP_502_BAD_GATEWAY
            )
        
        except Exception as e:
            logger.error(
                f"Error processing dedicated account for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return build_error_response(
                _("An unexpected error occurred. Please try again later."),
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )