from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from wallet.utils.id_generators import generate_transaction_reference
from wallet.models import Wallet, Transaction
from wallet.serializers.wallet_serializer import (
    WalletSerializer, WalletDetailSerializer, WalletCreateUpdateSerializer,
    WalletDepositSerializer, WalletWithdrawSerializer, WalletTransferSerializer
)
from django.conf import settings
from django.db import transaction
from wallet.serializers.transaction_serializer import TransactionSerializer
from wallet.services.wallet_service import WalletService
from django.utils import timezone
from wallet.services.wallet_service import WalletService
import logging
from wallet.serializers.wallet_serializer import FinalizeWithdrawalSerializer

logger = logging.getLogger(__name__)


class IsWalletOwner(permissions.BasePermission):
    """Permission to check if user is the wallet owner"""
    
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

def get_client_ip(request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')

class WalletViewSet(viewsets.ModelViewSet):
    """
    API endpoint for wallets
    """
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated, IsWalletOwner]
    
    def get_queryset(self):
        """Get wallets for the current user"""
        return Wallet.objects.filter(user=self.request.user)
    
    def get_serializer_class(self):
        """Return the appropriate serializer based on action"""
        if self.action == 'retrieve':
            return WalletDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return WalletCreateUpdateSerializer
        elif self.action == 'deposit':
            return WalletDepositSerializer
        elif self.action == 'withdraw':
            return WalletWithdrawSerializer
        elif self.action == 'transfer':
            return WalletTransferSerializer
        
        return self.serializer_class
    
    def get_object(self):
        """Get wallet object based on ID or user's default wallet"""
        if self.kwargs.get('pk') == 'default':
            # Get user's default wallet
            try:
                wallet = Wallet.objects.get(user=self.request.user)
                self.check_object_permissions(self.request, wallet)
                return wallet
            except Wallet.DoesNotExist:
                # Create a wallet if it doesn't exist
                wallet_service = WalletService()
                wallet = wallet_service.get_wallet(self.request.user)
                self.check_object_permissions(self.request, wallet)
                return wallet
        
        return super().get_object()
    
    def create(self, request, *args, **kwargs):
        """Create a new wallet for the user"""
        # Check if user already has a wallet
        if Wallet.objects.filter(user=request.user).exists():
            return Response(
                {"detail": _("User already has a wallet")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create wallet using the wallet service
        wallet_service = WalletService()
        wallet = wallet_service.get_wallet(request.user)
        
        # Update wallet with provided data
        serializer = self.get_serializer(wallet, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Return detailed wallet info
        return Response(
            WalletDetailSerializer(wallet).data,
            status=status.HTTP_201_CREATED
        )

    
    @action(detail=True, methods=['post'])
    def deposit(self, request, pk=None):
        """
        Initiate a deposit to the wallet
        
        This initializes a Paystack charge transaction and returns 
        the authorization URL for completing the payment
        """
        wallet = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        wallet_service = WalletService()
        
        try:
            # Initialize charge
            email = serializer.validated_data.get('email', request.user.email or '')
            callback_url = serializer.validated_data.get('callback_url', '')
            reference = serializer.validated_data.get('reference') or generate_transaction_reference()
            description = serializer.validated_data.get('description', 'Card deposit to wallet')
            # Get metadata and ensure it's a dict
            metadata = serializer.validated_data.get('metadata') or {}
            if not isinstance(metadata, dict):
                metadata = {}
            else:
                metadata = metadata.copy()  

            # Add request data to metadata
            metadata.update({
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                "description": description,
            })
            
            # Initialize Paystack transaction
            charge_data = wallet_service.initialize_card_charge(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                email=email,
                reference=reference,
                callback_url=callback_url,
                metadata = metadata
            )
            
            return Response(charge_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def withdraw(self, request, pk=None):
        """
        Withdraw funds from the wallet to a bank account
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Withdrawal initiated for wallet {wallet.id} by user {user_id}")
            
            # Validate request data
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid withdrawal data for wallet {wallet.id}: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            logger.debug(f"Withdrawal serializer validation passed for wallet {wallet.id}")
            
            wallet_service = WalletService()
            
            # Extract and validate required data
            try:
                bank_account_id = serializer.validated_data['bank_account_id']
                amount = serializer.validated_data['amount']
                description = serializer.validated_data.get('description')
                reference = serializer.validated_data.get('reference') or generate_transaction_reference()
                metadata = serializer.validated_data.get('metadata', {})
                if not isinstance(metadata, dict):
                    metadata = {}
                else:
                    metadata = metadata.copy()  

                # Add request data to metadata
                metadata.update({
                    'ip_address': get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                })
                
                
                logger.info(f"Processing withdrawal: wallet_id={wallet.id}, amount={amount}, bank_account_id={bank_account_id}, reference={reference}")
                
            except KeyError as e:
                logger.error(f"Missing required field in withdrawal request for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": f"Missing required field: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Get and validate bank account
                from wallet.models import BankAccount
                
                logger.debug(f"Fetching bank account {bank_account_id} for wallet {wallet.id}")
                
                bank_account = get_object_or_404(
                    BankAccount, 
                    id=bank_account_id,
                    wallet=wallet,
                    is_active=True
                )
                
                logger.info(f"Bank account validated: {bank_account.id} for wallet {wallet.id}")
                
            except Exception as e:
                logger.error(f"Bank account validation failed for withdrawal: wallet_id={wallet.id}, bank_account_id={bank_account_id}, error={str(e)}")
                return Response(
                    {"detail": "Invalid or inactive bank account"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Process withdrawal
                logger.info(f"Initiating withdrawal to bank for wallet {wallet.id}, amount {amount}")
                
                transaction, transfer_data = wallet_service.withdraw_to_bank(
                    wallet=wallet,
                    amount=amount,
                    bank_account=bank_account,
                    reason=description,
                    metadata=metadata,
                    reference=reference
                )
                
                logger.info(f"Withdrawal successful: wallet_id={wallet.id}, transaction_id={transaction.id}, reference={reference}")
                
            except ValueError as e:
                logger.error(f"Invalid withdrawal parameters for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": f"Invalid parameters: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except PermissionError as e:
                logger.error(f"Insufficient permissions for withdrawal: wallet_id={wallet.id}, error={str(e)}")
                return Response(
                    {"detail": "Insufficient funds or withdrawal limit exceeded"},
                    status=status.HTTP_403_FORBIDDEN
                )
            except ConnectionError as e:
                logger.error(f"Bank service connection failed for withdrawal {reference}: {str(e)}")
                return Response(
                    {"detail": "Banking service temporarily unavailable. Please try again later."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            except Exception as e:
                logger.error(f"Wallet service error during withdrawal for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Withdrawal failed. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Serialize transaction data
                from wallet.serializers.transaction_serializer import TransactionSerializer
                
                logger.debug(f"Serializing transaction data for transaction {transaction.id}")
                
                transaction_data = TransactionSerializer(transaction).data
                
                response_data = {
                    'transaction': transaction_data,
                    'transfer_data': transfer_data
                }
                
                logger.info(f"Withdrawal response prepared successfully for wallet {wallet.id}")
                logger.debug(f"Response data: {response_data}")
                
                return Response(response_data, status=status.HTTP_200_OK)
                
            except Exception as e:
                logger.error(f"Failed to serialize withdrawal response for transaction {transaction.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Withdrawal processed but response formatting failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in withdrawal endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
        
    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        """
        Transfer funds to another wallet
        """
        source_wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get source wallet
            source_wallet = self.get_object()
            logger.info(f"Transfer initiated from wallet {source_wallet.id} by user {user_id}")
            
            # Validate request data
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid transfer data for wallet {source_wallet.id}: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            logger.debug(f"Transfer serializer validation passed for wallet {source_wallet.id}")
            
            wallet_service = WalletService()
            
            # Extract and validate required data
            try:
                destination_wallet_id = serializer.validated_data['destination_wallet_id']
                amount = serializer.validated_data['amount']
                description = serializer.validated_data.get('description', '')
                metadata = serializer.validated_data.get('metadata', {})
                reference = serializer.validated_data.get('reference')
                
                logger.info(f"Processing transfer: source_wallet={source_wallet.id}, destination_wallet={destination_wallet_id}, amount={amount}, reference={reference}")
                
            except KeyError as e:
                logger.error(f"Missing required field in transfer request for wallet {source_wallet.id}: {str(e)}")
                return Response(
                    {"detail": f"Missing required field: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate amount (redundant check since serializer already validates, but keeping for extra safety)
            if amount <= 0:
                logger.warning(f"Invalid transfer amount {amount} for wallet {source_wallet.id}")
                return Response(
                    {"detail": "Transfer amount must be greater than zero"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check for self-transfer
            if str(destination_wallet_id) == str(source_wallet.id):
                logger.warning(f"Self-transfer attempted for wallet {source_wallet.id}")
                return Response(
                    {"detail": "Cannot transfer to the same wallet"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Get and validate destination wallet
                logger.debug(f"Fetching destination wallet {destination_wallet_id}")
                
                destination_wallet = get_object_or_404(
                    Wallet, 
                    id=destination_wallet_id, 
                    is_active=True
                )
                
                logger.info(f"Destination wallet validated: {destination_wallet.id}")
                
            except Exception as e:
                logger.error(f"Destination wallet validation failed: wallet_id={destination_wallet_id}, error={str(e)}")
                return Response(
                    {"detail": "Invalid or inactive destination wallet"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Import transaction service
                from wallet.services.transaction_service import TransactionService
                transaction_service = TransactionService()
                
                logger.debug(f"Transaction service initialized for transfer from wallet {source_wallet.id}")
                
            except ImportError as e:
                logger.error(f"Failed to import TransactionService: {str(e)}")
                return Response(
                    {"detail": "Service temporarily unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                # Perform the transfer
                logger.info(f"Executing transfer: {source_wallet.id} -> {destination_wallet.id}, amount={amount}")
                
                transaction = wallet_service.transfer(
                    source_wallet=source_wallet,
                    destination_wallet=destination_wallet,
                    amount=amount,
                    description=description,
                    metadata=metadata,
                    transaction_reference=reference
                )
                
                logger.info(f"Transfer successful: transaction_id={transaction.id}, reference={reference}")
                
            except ValueError as e:
                logger.error(f"Invalid transfer parameters: {str(e)}")
                return Response(
                    {"detail": f"Invalid transfer parameters: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except PermissionError as e:
                logger.error(f"Insufficient funds for transfer from wallet {source_wallet.id}: {str(e)}")
                return Response(
                    {"detail": "Insufficient funds for this transfer"},
                    status=status.HTTP_403_FORBIDDEN
                )
            except Exception as e:
                logger.error(f"Transfer execution failed for wallet {source_wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Transfer failed. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Serialize transaction data
                from wallet.serializers.transaction_serializer import TransactionSerializer
                
                logger.debug(f"Serializing transaction data for transaction {transaction.id}")
                
                transaction_data = TransactionSerializer(transaction).data
                
                logger.info(f"Transfer response prepared successfully for transaction {transaction.id}")
                
                return Response(transaction_data, status=status.HTTP_200_OK)
                
            except Exception as e:
                logger.error(f"Failed to serialize transfer response for transaction {transaction.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Transfer completed but response formatting failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = source_wallet.id if source_wallet else pk
            logger.error(f"Unexpected error in transfer endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """
        Get transactions for this wallet
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Transaction list requested for wallet {wallet.id} by user {user_id}")
            
            try:
                # Import transaction service
                from wallet.services.transaction_service import TransactionService
                transaction_service = TransactionService()
                
                logger.debug(f"Transaction service initialized for wallet {wallet.id}")
                
            except ImportError as e:
                logger.error(f"Failed to import TransactionService: {str(e)}")
                return Response(
                    {"detail": "Service temporarily unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                # Parse and validate query parameters
                transaction_type = request.query_params.get('type')
                status_param = request.query_params.get('status')
                
                # Validate and set pagination parameters
                try:
                    limit = int(request.query_params.get('limit', 20))
                    offset = int(request.query_params.get('offset', 0))
                    
                    # Validate pagination bounds
                    if limit < 1 or limit > 100:
                        logger.warning(f"Invalid limit parameter {limit} for wallet {wallet.id}")
                        limit = min(max(limit, 1), 100)
                    
                    if offset < 0:
                        logger.warning(f"Invalid offset parameter {offset} for wallet {wallet.id}")
                        offset = 0
                        
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid pagination parameters for wallet {wallet.id}: {str(e)}")
                    limit, offset = 20, 0
                
                logger.debug(f"Transaction query params: type={transaction_type}, status={status_param}, limit={limit}, offset={offset}")
                
            except Exception as e:
                logger.error(f"Error parsing query parameters for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": "Invalid query parameters"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Get transactions
                logger.debug(f"Fetching transactions for wallet {wallet.id}")
                
                transactions = transaction_service.list_transactions(
                    wallet=wallet,
                    transaction_type=transaction_type,
                    status=status_param,
                    limit=limit,
                    offset=offset
                )
                
                logger.info(f"Retrieved {transactions.count()} transactions for wallet {wallet.id}")
                
            except Exception as e:
                logger.error(f"Failed to fetch transactions for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to retrieve transactions"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Serialize transactions
                from wallet.serializers.transaction_serializer import TransactionListSerializer
                
                logger.debug(f"Serializing {transactions.count()} transactions for wallet {wallet.id}")
                
                transaction_data = TransactionListSerializer(transactions, many=True).data
                
                # Prepare pagination info
                total_count = transactions.count()
                next_offset = offset + limit if offset + limit < total_count else None
                previous_offset = offset - limit if offset > 0 else None
                
                response_data = {
                    'count': total_count,
                    'next': next_offset,
                    'previous': previous_offset,
                    'results': transaction_data
                }
                
                logger.info(f"Transaction list response prepared for wallet {wallet.id}: {total_count} total, {len(transaction_data)} returned")
                
                return Response(response_data, status=status.HTTP_200_OK)
                
            except Exception as e:
                logger.error(f"Failed to serialize transactions for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to format transaction data"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in transactions endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        """
        Get the current balance of the wallet
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Balance requested for wallet {wallet.id} by user {user_id}")
            
            try:
                # Initialize wallet service
                wallet_service = WalletService()
                logger.debug(f"Wallet service initialized for balance check of wallet {wallet.id}")
                
            except Exception as e:
                logger.error(f"Failed to initialize WalletService: {str(e)}")
                return Response(
                    {"detail": "Service temporarily unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                # Get balance
                logger.debug(f"Fetching balance for wallet {wallet.id}")
                
                balance = wallet_service.get_balance(wallet)
                
                logger.info(f"Balance retrieved for wallet {wallet.id}: {balance.amount} {getattr(balance.currency, 'code', 'N/A')}")
                
            except AttributeError as e:
                logger.error(f"Balance object structure error for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": "Invalid balance data structure"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            except Exception as e:
                logger.error(f"Failed to retrieve balance for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to retrieve wallet balance"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Prepare response data
                currency_code = getattr(balance.currency, 'code', 'USD')
                balance_amount = str(balance.amount) if hasattr(balance, 'amount') else '0.00'
                
                response_data = {
                    'balance': balance_amount,
                    'currency': currency_code
                }
                
                logger.debug(f"Balance response prepared for wallet {wallet.id}: {response_data}")
                
                return Response(response_data, status=status.HTTP_200_OK)
                
            except Exception as e:
                logger.error(f"Failed to format balance response for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to format balance data"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in balance endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        """
        Lock the wallet to prevent transactions
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Wallet lock requested for wallet {wallet.id} by user {user_id}")
            
            # Check if wallet is already locked
            if hasattr(wallet, 'is_locked') and wallet.is_locked:
                logger.warning(f"Attempt to lock already locked wallet {wallet.id}")
                return Response(
                    {"detail": _("Wallet is already locked")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Lock the wallet
                logger.debug(f"Executing lock operation for wallet {wallet.id}")
                wallet.lock()
                
                logger.info(f"Wallet {wallet.id} successfully locked by user {user_id}")
                
                return Response(
                    {"detail": _("Wallet locked successfully")},
                    status=status.HTTP_200_OK
                )
                
            except AttributeError as e:
                logger.error(f"Wallet lock method not available for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": "Wallet lock functionality not available"},
                    status=status.HTTP_501_NOT_IMPLEMENTED
                )
            except Exception as e:
                logger.error(f"Failed to lock wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to lock wallet. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in wallet lock endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        """
        Unlock the wallet to allow transactions
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Wallet unlock requested for wallet {wallet.id} by user {user_id}")
            
            # Check if wallet is already unlocked
            if hasattr(wallet, 'is_locked') and not wallet.is_locked:
                logger.warning(f"Attempt to unlock already unlocked wallet {wallet.id}")
                return Response(
                    {"detail": _("Wallet is already unlocked")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Unlock the wallet
                logger.debug(f"Executing unlock operation for wallet {wallet.id}")
                wallet.unlock()
                
                logger.info(f"Wallet {wallet.id} successfully unlocked by user {user_id}")
                
                return Response(
                    {"detail": _("Wallet unlocked successfully")},
                    status=status.HTTP_200_OK
                )
                
            except AttributeError as e:
                logger.error(f"Wallet unlock method not available for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": "Wallet unlock functionality not available"},
                    status=status.HTTP_501_NOT_IMPLEMENTED
                )
            except Exception as e:
                logger.error(f"Failed to unlock wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to unlock wallet. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in wallet unlock endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def cards(self, request, pk=None):
        """
        Get cards associated with this wallet
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Cards list requested for wallet {wallet.id} by user {user_id}")
            
            try:
                # Import Card model
                from wallet.models import Card
                logger.debug(f"Card model imported successfully for wallet {wallet.id}")
                
            except ImportError as e:
                logger.error(f"Failed to import Card model: {str(e)}")
                return Response(
                    {"detail": "Card service temporarily unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                # Get cards
                logger.debug(f"Fetching active cards for wallet {wallet.id}")
                
                cards = Card.objects.filter(wallet=wallet, is_active=True)
                card_count = cards.count()
                
                logger.info(f"Retrieved {card_count} active cards for wallet {wallet.id}")
                
            except Exception as e:
                logger.error(f"Failed to fetch cards for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to retrieve cards"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Serialize cards
                from wallet.serializers.card_serializer import CardSerializer
                
                logger.debug(f"Serializing {card_count} cards for wallet {wallet.id}")
                
                card_data = CardSerializer(cards, many=True).data
                
                logger.info(f"Cards response prepared for wallet {wallet.id}: {len(card_data)} cards serialized")
                
                return Response(card_data, status=status.HTTP_200_OK)
                
            except ImportError as e:
                logger.error(f"Failed to import CardSerializer: {str(e)}")
                return Response(
                    {"detail": "Card serialization service unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            except Exception as e:
                logger.error(f"Failed to serialize cards for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to format card data"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in cards endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def bank_accounts(self, request, pk=None):
        """
        Get bank accounts associated with this wallet
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Bank accounts list requested for wallet {wallet.id} by user {user_id}")
            
            try:
                # Import BankAccount model
                from wallet.models import BankAccount
                logger.debug(f"BankAccount model imported successfully for wallet {wallet.id}")
                
            except ImportError as e:
                logger.error(f"Failed to import BankAccount model: {str(e)}")
                return Response(
                    {"detail": "Bank account service temporarily unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                # Get bank accounts
                logger.debug(f"Fetching active bank accounts for wallet {wallet.id}")
                
                bank_accounts = BankAccount.objects.filter(wallet=wallet, is_active=True)
                account_count = bank_accounts.count()
                
                logger.info(f"Retrieved {account_count} active bank accounts for wallet {wallet.id}")
                
            except Exception as e:
                logger.error(f"Failed to fetch bank accounts for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to retrieve bank accounts"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Serialize bank accounts
                from wallet.serializers.bank_account_serializer import BankAccountSerializer
                
                logger.debug(f"Serializing {account_count} bank accounts for wallet {wallet.id}")
                
                bank_account_data = BankAccountSerializer(bank_accounts, many=True).data
                
                logger.info(f"Bank accounts response prepared for wallet {wallet.id}: {len(bank_account_data)} accounts serialized")
                
                return Response(bank_account_data, status=status.HTTP_200_OK)
                
            except ImportError as e:
                logger.error(f"Failed to import BankAccountSerializer: {str(e)}")
                return Response(
                    {"detail": "Bank account serialization service unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            except Exception as e:
                logger.error(f"Failed to serialize bank accounts for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to format bank account data"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in bank_accounts endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def dedicated_account(self, request, pk=None):
        """
        Get or create dedicated virtual account for this wallet
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            # Get wallet object
            wallet = self.get_object()
            logger.info(f"Dedicated account requested for wallet {wallet.id} by user {user_id}")
            
            try:
                # Initialize wallet service
                wallet_service = WalletService()
                logger.debug(f"WalletService initialized for dedicated account operation on wallet {wallet.id}")
                
            except Exception as e:
                logger.error(f"Failed to initialize WalletService: {str(e)}")
                return Response(
                    {"detail": "Wallet service temporarily unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            # Check if wallet already has a dedicated account
            try:
                if hasattr(wallet, 'dedicated_account_number') and wallet.dedicated_account_number:
                    logger.info(f"Existing dedicated account found for wallet {wallet.id}: {wallet.dedicated_account_number}")
                    
                    # Get account name safely
                    try:
                        if hasattr(wallet.user, 'get_full_name'):
                            account_name = wallet.user.get_full_name()
                        else:
                            account_name = str(wallet.user)
                    except Exception as e:
                        logger.warning(f"Failed to get user full name for wallet {wallet.id}: {str(e)}")
                        account_name = f"User {wallet.user.id}" if hasattr(wallet, 'user') else "Unknown User"
                    
                    response_data = {
                        'account_number': wallet.dedicated_account_number,
                        'bank_name': getattr(wallet, 'dedicated_account_bank', 'N/A'),
                        'account_name': account_name
                    }
                    
                    logger.debug(f"Existing dedicated account response for wallet {wallet.id}: {response_data}")
                    
                    return Response(response_data, status=status.HTTP_200_OK)
                    
            except AttributeError as e:
                logger.debug(f"Dedicated account attributes not found for wallet {wallet.id}: {str(e)}")
                # Continue to create new account
            
            try:
                # Create dedicated account
                logger.info(f"Creating new dedicated account for wallet {wallet.id}")
                
                success = wallet_service.create_dedicated_account(wallet)
                
                if success:
                    logger.info(f"Dedicated account created successfully for wallet {wallet.id}")
                    
                    # Refresh wallet to get updated account details
                    try:
                        wallet.refresh_from_db()
                    except Exception as e:
                        logger.warning(f"Failed to refresh wallet {wallet.id} from database: {str(e)}")
                    
                    # Get account name safely
                    try:
                        if hasattr(wallet.user, 'get_full_name'):
                            account_name = wallet.user.get_full_name()
                        else:
                            account_name = str(wallet.user)
                    except Exception as e:
                        logger.warning(f"Failed to get user full name for wallet {wallet.id}: {str(e)}")
                        account_name = f"User {wallet.user.id}" if hasattr(wallet, 'user') else "Unknown User"
                    
                    response_data = {
                        'account_number': getattr(wallet, 'dedicated_account_number', 'N/A'),
                        'bank_name': getattr(wallet, 'dedicated_account_bank', 'N/A'),
                        'account_name': account_name
                    }
                    
                    logger.info(f"New dedicated account response for wallet {wallet.id}: account_number={response_data['account_number']}")
                    
                    return Response(response_data, status=status.HTTP_200_OK)
                else:
                    logger.error(f"Failed to create dedicated account for wallet {wallet.id}: service returned false")
                    return Response(
                        {"detail": _("Could not create dedicated account")},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                    
            except ConnectionError as e:
                logger.error(f"Connection error while creating dedicated account for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": "Banking service temporarily unavailable. Please try again later."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            except ValueError as e:
                logger.error(f"Invalid parameters for dedicated account creation for wallet {wallet.id}: {str(e)}")
                return Response(
                    {"detail": f"Invalid account parameters: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Exception as e:
                logger.error(f"Failed to create dedicated account for wallet {wallet.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to create dedicated account. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in dedicated_account endpoint for wallet {wallet_id} by user {user_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

    @action(detail=True, methods=['post'])
    def finalize_withdrawal(self, request, pk=None):
        """
        Finalize a withdrawal that requires OTP verification
        
        Expected payload:
        {
            "transfer_code": "TRF_xxxxx",
            "otp": "123456"
        }
        """
        wallet = None
        user_id = getattr(request.user, 'id', 'Anonymous')
        
        try:
            wallet = self.get_object()
            logger.info(f"Finalizing withdrawal for wallet {wallet.id} by user {user_id}")
            
            # Use serializer for validation
            serializer = FinalizeWithdrawalSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid finalization data for wallet {wallet.id}: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            transfer_code = serializer.validated_data['transfer_code']
            otp = serializer.validated_data['otp']
            
            logger.debug(f"Finalization request: transfer_code={transfer_code}, wallet_id={wallet.id}")
            
            # Find the transaction by transfer_code
            try:
                from wallet.models import Transaction
                from wallet.constants import TRANSACTION_TYPE_WITHDRAWAL, TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED
                
                transaction = Transaction.objects.get(
                    wallet=wallet,
                    paystack_reference=transfer_code,
                    transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
                    status=TRANSACTION_STATUS_PENDING
                )
                logger.info(f"Found pending transaction {transaction.id} for finalization")
                
            except Transaction.DoesNotExist:
                logger.error(f"Transaction not found for transfer_code {transfer_code} and wallet {wallet.id}")
                return Response(
                    {"detail": "Transaction not found or already processed"},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                logger.error(f"Error finding transaction for transfer_code {transfer_code}: {str(e)}")
                return Response(
                    {"detail": "Error retrieving transaction"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            wallet_service = WalletService()
            
            try:
                # Finalize the transfer with Paystack
                logger.info(f"Finalizing transfer {transfer_code} with OTP for transaction {transaction.id}")
                
                finalize_data = wallet_service.finalize_transfer(
                    transfer_code=transfer_code,
                    otp=otp
                )
                
                logger.debug(f"Paystack finalize response: {finalize_data}")
                
                # Update transaction based on result
                if finalize_data.get('status') and finalize_data.get('data', {}).get('status') == 'success':
                    transaction.status = TRANSACTION_STATUS_SUCCESS
                    transaction.completed_at = timezone.now()
                    transaction.paystack_response = finalize_data
                    transaction.save(update_fields=['status', 'completed_at', 'paystack_response'])
                    
                    logger.info(f"Transaction {transaction.id} finalized successfully")
                    
                else:
                    # Transfer failed - mark as failed and refund wallet
                    error_message = finalize_data.get('message', 'OTP verification failed nze delete')
                    transaction.status = TRANSACTION_STATUS_FAILED
                    transaction.failed_reason = error_message
                    
                    # Refund wallet if transfer failed
                    try:
                        wallet.deposit(transaction.amount)
                        logger.info(f"Refunded {transaction.amount} to wallet {wallet.id} after failed OTP")
                    except Exception as refund_error:
                        logger.error(f"Error refunding wallet {wallet.id} after failed OTP: {str(refund_error)}")
                        # Still save the transaction as failed
                    
                    transaction.save(update_fields=['status', 'failed_reason'])
                    logger.error(f"Transaction {transaction.id} finalization failed: {error_message}")
                
            except ValueError as e:
                logger.error(f"Invalid OTP or transfer_code for transaction {transaction.id}: {str(e)}")
                return Response(
                    {"detail": "Invalid OTP or transfer code"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except ConnectionError as e:
                logger.error(f"Paystack connection error during finalization {transfer_code}: {str(e)}")
                return Response(
                    {"detail": "Payment service temporarily unavailable. Please try again later."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            except Exception as e:
                logger.error(f"Error finalizing transfer {transfer_code}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Failed to finalize withdrawal. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            try:
                # Serialize response
                from wallet.serializers.transaction_serializer import TransactionSerializer
                transaction_data = TransactionSerializer(transaction).data
                
                response_data = {
                    'transaction': transaction_data,
                    'finalize_data': finalize_data
                }
                
                logger.info(f"Finalization response prepared for transaction {transaction.id}")
                return Response(response_data, status=status.HTTP_200_OK)
                
            except Exception as e:
                logger.error(f"Error serializing finalization response for transaction {transaction.id}: {str(e)}", exc_info=True)
                return Response(
                    {"detail": "Finalization processed but response formatting failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            wallet_id = wallet.id if wallet else pk
            logger.error(f"Unexpected error in finalize_withdrawal for wallet {wallet_id}: {str(e)}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )