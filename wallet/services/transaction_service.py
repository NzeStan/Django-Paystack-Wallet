"""
Django Paystack Wallet - Transaction Service Layer
Refactored with improved organization, error handling, and comprehensive operations
"""
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, List
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Count, Avg, Q

from wallet.models import Transaction, Wallet
from wallet.constants import (
    TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_SUCCESS, 
    TRANSACTION_STATUS_FAILED, TRANSACTION_STATUS_CANCELLED,
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_TYPE_WITHDRAWAL, 
    TRANSACTION_TYPE_TRANSFER, TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_REFUND, TRANSACTION_TYPE_REVERSAL,
    TRANSACTION_TYPES, TRANSACTION_STATUSES
)
from wallet.exceptions import (
    TransactionFailed,
    InsufficientFunds,
    InvalidAmount,
    WalletLocked
)
from wallet.settings import get_wallet_setting
from wallet.utils.id_generators import generate_transaction_reference


logger = logging.getLogger(__name__)


class TransactionService:
    """
    Service layer for transaction operations
    
    This service encapsulates all business logic related to transaction operations,
    including creation, updates, bulk operations, and statistics.
    
    All monetary operations are wrapped in database transactions to ensure
    data consistency and integrity.
    """
    
    # ==========================================
    # TRANSACTION RETRIEVAL
    # ==========================================
    
    def get_transaction(self, transaction_id: Any, for_update: bool = False) -> Transaction:
        """
        Get a transaction by ID
        
        Args:
            transaction_id: Transaction ID
            for_update: Whether to lock the transaction for update
            
        Returns:
            Transaction: Transaction object
            
        Raises:
            Transaction.DoesNotExist: If transaction not found
        """
        queryset = Transaction.objects.all()
        
        if for_update:
            queryset = queryset.select_for_update()
            logger.debug(f"Fetching transaction {transaction_id} with SELECT FOR UPDATE lock")
        
        try:
            transaction = queryset.get(id=transaction_id)
            logger.debug(f"Retrieved transaction {transaction_id}")
            return transaction
        except Transaction.DoesNotExist:
            logger.error(f"Transaction {transaction_id} not found")
            raise
    
    def get_transaction_by_reference(
        self, 
        reference: str, 
        for_update: bool = False
    ) -> Transaction:
        """
        Get a transaction by reference
        
        Args:
            reference: Transaction reference
            for_update: Whether to lock the transaction for update
            
        Returns:
            Transaction: Transaction object
            
        Raises:
            Transaction.DoesNotExist: If transaction not found
        """
        queryset = Transaction.objects.all()
        
        if for_update:
            queryset = queryset.select_for_update()
            logger.debug(f"Fetching transaction with reference {reference} with lock")
        
        try:
            transaction = queryset.get(reference=reference)
            logger.debug(f"Retrieved transaction with reference {reference}")
            return transaction
        except Transaction.DoesNotExist:
            logger.error(f"Transaction with reference {reference} not found")
            raise
    
    def list_transactions(
        self,
        wallet: Optional[Wallet] = None,
        status: Optional[str] = None,
        transaction_type: Optional[str] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ):
        """
        List transactions with optional filtering
        
        Args:
            wallet: Filter by wallet
            status: Filter by status
            transaction_type: Filter by transaction type
            start_date: Filter by start date
            end_date: Filter by end date
            min_amount: Filter by minimum amount
            max_amount: Filter by maximum amount
            limit: Limit number of results
            offset: Offset for pagination
            
        Returns:
            QuerySet: Filtered transactions
        """
        queryset = Transaction.objects.with_wallet_details()
        
        if wallet:
            queryset = queryset.by_wallet(wallet)
            logger.debug(f"Filtering transactions for wallet {wallet.id}")
            
        if status:
            queryset = queryset.filter(status=status)
            logger.debug(f"Filtering transactions by status: {status}")
            
        if transaction_type:
            queryset = queryset.by_type(transaction_type)
            logger.debug(f"Filtering transactions by type: {transaction_type}")
            
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
            logger.debug(f"Filtering transactions by date range: {start_date} to {end_date}")
        
        if min_amount is not None or max_amount is not None:
            queryset = queryset.by_amount_range(min_amount, max_amount)
            logger.debug(f"Filtering transactions by amount range: {min_amount} to {max_amount}")
        
        queryset = queryset.order_by('-created_at')
        
        if offset is not None:
            queryset = queryset[offset:]
            
        if limit is not None:
            queryset = queryset[:limit]
        
        logger.info(f"Listed {queryset.count()} transactions with applied filters")
        return queryset
    
    # ==========================================
    # TRANSACTION CREATION
    # ==========================================
    
    def create_transaction(
        self,
        wallet: Wallet,
        amount: Decimal,
        transaction_type: str,
        status: str = TRANSACTION_STATUS_PENDING,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None,
        **kwargs
    ) -> Transaction:
        """
        Create a new transaction
        
        Args:
            wallet: Wallet for the transaction
            amount: Transaction amount
            transaction_type: Type of transaction
            status: Transaction status
            description: Description of the transaction
            metadata: Additional metadata
            reference: Transaction reference
            **kwargs: Additional fields for the transaction
            
        Returns:
            Transaction: Created transaction
        """
        if reference is None:
            reference = generate_transaction_reference()
            
        transaction = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=transaction_type,
            status=status,
            description=description,
            metadata=metadata or {},
            reference=reference,
            **kwargs
        )
        
        logger.info(
            f"Created transaction {transaction.id}: "
            f"wallet={wallet.id}, type={transaction_type}, "
            f"amount={amount}, status={status}, reference={reference}"
        )
        
        return transaction
    
    def bulk_create_transactions(
        self,
        transactions_data: List[Dict[str, Any]]
    ) -> List[Transaction]:
        """
        Bulk create multiple transactions
        
        Args:
            transactions_data: List of transaction data dictionaries
            
        Returns:
            List[Transaction]: Created transactions
            
        Example:
            transactions_data = [
                {
                    'wallet': wallet1,
                    'amount': 100,
                    'transaction_type': 'deposit',
                    'description': 'Bulk deposit 1'
                },
                {
                    'wallet': wallet2,
                    'amount': 200,
                    'transaction_type': 'deposit',
                    'description': 'Bulk deposit 2'
                }
            ]
        """
        transactions = []
        
        for data in transactions_data:
            # Generate reference if not provided
            if 'reference' not in data or data['reference'] is None:
                data['reference'] = generate_transaction_reference()
            
            # Set default status if not provided
            if 'status' not in data:
                data['status'] = TRANSACTION_STATUS_PENDING
            
            # Set default metadata if not provided
            if 'metadata' not in data:
                data['metadata'] = {}
            
            transactions.append(Transaction(**data))
        
        # Bulk create
        created_transactions = Transaction.objects.bulk_create(transactions)
        
        logger.info(f"Bulk created {len(created_transactions)} transactions")
        
        return created_transactions
    
    # ==========================================
    # TRANSACTION STATUS UPDATES
    # ==========================================
    
    @db_transaction.atomic
    def mark_transaction_as_success(
        self,
        transaction: Transaction,
        paystack_data: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Mark a transaction as successful
        
        Args:
            transaction: Transaction to update
            paystack_data: Paystack response data
            
        Returns:
            Transaction: Updated transaction
        """
        transaction = self.get_transaction(transaction.id, for_update=True)
        
        if transaction.status == TRANSACTION_STATUS_SUCCESS:
            logger.warning(f"Transaction {transaction.id} is already successful")
            return transaction
        
        # Update transaction
        transaction.status = TRANSACTION_STATUS_SUCCESS
        transaction.completed_at = timezone.now()
        
        if paystack_data:
            transaction.paystack_response = paystack_data
            
            if 'reference' in paystack_data:
                transaction.paystack_reference = paystack_data['reference']
        
        transaction.save(update_fields=[
            'status', 'completed_at', 'paystack_response', 
            'paystack_reference', 'updated_at'
        ])
        
        logger.info(
            f"Marked transaction {transaction.id} as successful: "
            f"type={transaction.transaction_type}, amount={transaction.amount}"
        )
        
        # Perform actions based on transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_DEPOSIT:
            # Credit the wallet if not already credited
            if transaction.wallet.balance.amount < transaction.amount.amount:
                logger.debug(
                    f"Crediting wallet {transaction.wallet.id} with "
                    f"{transaction.amount.amount} for transaction {transaction.id}"
                )
        
        return transaction
    
    @db_transaction.atomic
    def mark_transaction_as_failed(
        self,
        transaction: Transaction,
        reason: Optional[str] = None,
        paystack_data: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Mark a transaction as failed
        
        Args:
            transaction: Transaction to update
            reason: Reason for failure
            paystack_data: Paystack response data
            
        Returns:
            Transaction: Updated transaction
        """
        transaction = self.get_transaction(transaction.id, for_update=True)
        
        if transaction.status == TRANSACTION_STATUS_FAILED:
            logger.warning(f"Transaction {transaction.id} is already failed")
            return transaction
        
        # Update transaction
        transaction.status = TRANSACTION_STATUS_FAILED
        transaction.failed_reason = reason or _("Transaction failed")
        transaction.completed_at = timezone.now()
        
        if paystack_data:
            transaction.paystack_response = paystack_data
        
        transaction.save(update_fields=[
            'status', 'failed_reason', 'completed_at', 
            'paystack_response', 'updated_at'
        ])
        
        logger.error(
            f"Marked transaction {transaction.id} as failed: "
            f"type={transaction.transaction_type}, amount={transaction.amount}, "
            f"reason={reason}"
        )
        
        # Perform actions based on transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            # Refund the wallet
            try:
                transaction.wallet.deposit(transaction.amount.amount)
                logger.info(
                    f"Refunded wallet {transaction.wallet.id} with "
                    f"{transaction.amount.amount} for failed transaction {transaction.id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to refund wallet {transaction.wallet.id} "
                    f"for transaction {transaction.id}: {str(e)}",
                    exc_info=True
                )
        
        return transaction
    
    @db_transaction.atomic
    def cancel_transaction(
        self,
        transaction: Transaction,
        reason: Optional[str] = None
    ) -> Transaction:
        """
        Cancel a pending transaction
        
        Args:
            transaction: Transaction to cancel
            reason: Reason for cancellation
            
        Returns:
            Transaction: Updated transaction
            
        Raises:
            ValueError: If transaction is not in pending status
        """
        transaction = self.get_transaction(transaction.id, for_update=True)
        
        if not transaction.can_be_cancelled():
            error_msg = _("Only pending transactions can be cancelled")
            logger.error(
                f"Cannot cancel transaction {transaction.id}: "
                f"status={transaction.status}"
            )
            raise ValueError(error_msg)
        
        # Update transaction
        transaction.status = TRANSACTION_STATUS_CANCELLED
        transaction.failed_reason = reason or _("Transaction cancelled")
        transaction.completed_at = timezone.now()
        transaction.save(update_fields=[
            'status', 'failed_reason', 'completed_at', 'updated_at'
        ])
        
        logger.info(
            f"Cancelled transaction {transaction.id}: "
            f"type={transaction.transaction_type}, amount={transaction.amount}, "
            f"reason={reason}"
        )
        
        # Perform actions based on transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            # Refund the wallet
            try:
                transaction.wallet.deposit(transaction.amount.amount)
                logger.info(
                    f"Refunded wallet {transaction.wallet.id} with "
                    f"{transaction.amount.amount} for cancelled transaction {transaction.id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to refund wallet {transaction.wallet.id} "
                    f"for cancelled transaction {transaction.id}: {str(e)}",
                    exc_info=True
                )
        
        return transaction
    
    # ==========================================
    # REFUND & REVERSAL OPERATIONS
    # ==========================================
    
    @db_transaction.atomic
    def refund_transaction(
        self,
        transaction: Transaction,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None
    ) -> Transaction:
        """
        Create a refund for a transaction
        
        Args:
            transaction: Transaction to refund
            amount: Amount to refund, defaults to full amount
            reason: Reason for refund
            
        Returns:
            Transaction: Refund transaction
            
        Raises:
            ValueError: If transaction cannot be refunded
        """
        transaction = self.get_transaction(transaction.id)
        
        if not transaction.can_be_refunded():
            error_msg = _(
                "Only successful deposit and payment transactions can be refunded"
            )
            logger.error(
                f"Cannot refund transaction {transaction.id}: "
                f"status={transaction.status}, type={transaction.transaction_type}"
            )
            raise ValueError(error_msg)
        
        # Determine refund amount
        if amount is None:
            amount = transaction.amount.amount
        else:
            amount = Decimal(str(amount))
            
            if amount > transaction.amount.amount:
                error_msg = _("Refund amount cannot exceed original transaction amount")
                logger.error(
                    f"Invalid refund amount for transaction {transaction.id}: "
                    f"refund={amount}, original={transaction.amount.amount}"
                )
                raise ValueError(error_msg)
        
        # Create refund transaction
        refund_transaction = self.create_transaction(
            wallet=transaction.wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_REFUND,
            status=TRANSACTION_STATUS_PENDING,
            description=reason or _("Refund for transaction {reference}").format(
                reference=transaction.reference
            ),
            related_transaction=transaction
        )
        
        logger.info(
            f"Created refund transaction {refund_transaction.id} for "
            f"transaction {transaction.id}: amount={amount}, reason={reason}"
        )
        
        # Process refund
        if transaction.transaction_type == TRANSACTION_TYPE_PAYMENT:
            # Credit the wallet
            try:
                transaction.wallet.deposit(amount)
                
                # Update refund transaction
                refund_transaction.status = TRANSACTION_STATUS_SUCCESS
                refund_transaction.completed_at = timezone.now()
                refund_transaction.save(update_fields=[
                    'status', 'completed_at', 'updated_at'
                ])
                
                logger.info(
                    f"Refund transaction {refund_transaction.id} processed successfully"
                )
            except Exception as e:
                # Mark refund as failed
                refund_transaction.status = TRANSACTION_STATUS_FAILED
                refund_transaction.failed_reason = str(e)
                refund_transaction.save(update_fields=[
                    'status', 'failed_reason', 'updated_at'
                ])
                
                logger.error(
                    f"Refund transaction {refund_transaction.id} failed: {str(e)}",
                    exc_info=True
                )
                raise
        
        return refund_transaction
    
    @db_transaction.atomic
    def reverse_transaction(
        self,
        transaction: Transaction,
        reason: Optional[str] = None
    ) -> Transaction:
        """
        Create a reversal for a transaction
        
        Args:
            transaction: Transaction to reverse
            reason: Reason for reversal
            
        Returns:
            Transaction: Reversal transaction
            
        Raises:
            ValueError: If transaction cannot be reversed
        """
        transaction = self.get_transaction(transaction.id)
        
        if not transaction.can_be_reversed():
            error_msg = _("Only successful transactions can be reversed")
            logger.error(
                f"Cannot reverse transaction {transaction.id}: "
                f"status={transaction.status}"
            )
            raise ValueError(error_msg)
        
        # Create reversal transaction
        reversal_transaction = self.create_transaction(
            wallet=transaction.wallet,
            amount=transaction.amount.amount,
            transaction_type=TRANSACTION_TYPE_REVERSAL,
            status=TRANSACTION_STATUS_PENDING,
            description=reason or _("Reversal for transaction {reference}").format(
                reference=transaction.reference
            ),
            related_transaction=transaction
        )
        
        logger.info(
            f"Created reversal transaction {reversal_transaction.id} for "
            f"transaction {transaction.id}: amount={transaction.amount.amount}, "
            f"reason={reason}"
        )
        
        # Process reversal based on original transaction type
        try:
            if transaction.transaction_type == TRANSACTION_TYPE_DEPOSIT:
                # Debit the wallet
                transaction.wallet.withdraw(transaction.amount.amount)
                
            elif transaction.transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
                # Credit the wallet
                transaction.wallet.deposit(transaction.amount.amount)
            
            # Update reversal transaction
            reversal_transaction.status = TRANSACTION_STATUS_SUCCESS
            reversal_transaction.completed_at = timezone.now()
            reversal_transaction.save(update_fields=[
                'status', 'completed_at', 'updated_at'
            ])
            
            logger.info(
                f"Reversal transaction {reversal_transaction.id} processed successfully"
            )
            
        except Exception as e:
            # Mark reversal as failed
            reversal_transaction.status = TRANSACTION_STATUS_FAILED
            reversal_transaction.failed_reason = str(e)
            reversal_transaction.save(update_fields=[
                'status', 'failed_reason', 'updated_at'
            ])
            
            logger.error(
                f"Reversal transaction {reversal_transaction.id} failed: {str(e)}",
                exc_info=True
            )
            raise
        
        return reversal_transaction
    
    # ==========================================
    # TRANSFER OPERATIONS
    # ==========================================
    
    @db_transaction.atomic
    def transfer_between_wallets(
        self,
        source_wallet: Wallet,
        destination_wallet: Wallet,
        amount: Decimal,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None
    ) -> Transaction:
        """
        Transfer funds between wallets
        
        This method is called by the API and wraps the wallet service transfer
        with transaction creation and tracking. It creates a transfer transaction
        and moves funds from source to destination wallet.
        
        The operation is atomic - either both wallets are updated or neither is.
        
        Args:
            source_wallet: Wallet to transfer from
            destination_wallet: Wallet to transfer to
            amount: Amount to transfer
            description: Transfer description
            metadata: Additional metadata
            reference: Transaction reference
            
        Returns:
            Transaction: Created transfer transaction
            
        Raises:
            WalletLocked: If either wallet is locked or inactive
            InvalidAmount: If amount is invalid
            InsufficientFunds: If source wallet has insufficient funds
        """
        # Validate amount
        amount = Decimal(str(amount))
        if amount <= 0:
            error_msg = _("Transfer amount must be greater than zero")
            logger.error(f"Invalid transfer amount: {amount}")
            raise InvalidAmount(error_msg)
        
        # Check wallet states
        if not source_wallet.is_active or source_wallet.is_locked:
            error_msg = _("Source wallet is locked or inactive")
            logger.error(
                f"Cannot transfer from wallet {source_wallet.id}: "
                f"active={source_wallet.is_active}, locked={source_wallet.is_locked}"
            )
            raise WalletLocked(error_msg)
        
        if not destination_wallet.is_active or destination_wallet.is_locked:
            error_msg = _("Destination wallet is locked or inactive")
            logger.error(
                f"Cannot transfer to wallet {destination_wallet.id}: "
                f"active={destination_wallet.is_active}, "
                f"locked={destination_wallet.is_locked}"
            )
            raise WalletLocked(error_msg)
        
        # Check sufficient funds
        if source_wallet.balance.amount < amount:
            error_msg = _("Insufficient funds in source wallet")
            logger.error(
                f"Insufficient funds for transfer from wallet {source_wallet.id}: "
                f"balance={source_wallet.balance.amount}, required={amount}"
            )
            raise InsufficientFunds(source_wallet, amount)
        
        # Default description
        if not description:
            destination_user = getattr(
                destination_wallet.user, 'email', str(destination_wallet.user)
            )
            description = _("Transfer to {recipient}").format(
                recipient=destination_user
            )
        
        if not reference:
            reference = generate_transaction_reference()
        
        # Create pending transaction
        txn = self.create_transaction(
            wallet=source_wallet,
            recipient_wallet=destination_wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=reference
        )
        
        logger.info(
            f"Created transfer transaction {txn.id}: "
            f"from_wallet={source_wallet.id}, to_wallet={destination_wallet.id}, "
            f"amount={amount}, reference={reference}"
        )
        
        try:
            # Execute transfer
            source_wallet.transfer(destination_wallet, amount, description)
            
            # Mark transaction as successful
            txn.status = TRANSACTION_STATUS_SUCCESS
            txn.completed_at = timezone.now()
            txn.save(update_fields=['status', 'completed_at', 'updated_at'])
            
            logger.info(
                f"Transfer transaction {txn.id} completed successfully: "
                f"from_wallet={source_wallet.id}, to_wallet={destination_wallet.id}, "
                f"amount={amount}"
            )
            
            return txn
        
        except Exception as e:
            # Mark transaction as failed
            txn.status = TRANSACTION_STATUS_FAILED
            txn.failed_reason = str(e)
            txn.save(update_fields=['status', 'failed_reason', 'updated_at'])
            
            logger.error(
                f"Transfer transaction {txn.id} failed: {str(e)}", 
                exc_info=True
            )
            
            # Re-raise the exception
            raise TransactionFailed(str(e)) from e
    
    # ==========================================
    # STATISTICS & ANALYTICS
    # ==========================================
    
    def get_transaction_statistics(
        self,
        wallet: Optional[Wallet] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Get transaction statistics for a wallet or globally
        
        Args:
            wallet: Filter by wallet (optional)
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            dict: Transaction statistics including counts, totals, and averages
        """
        queryset = Transaction.objects.all()
        
        if wallet:
            queryset = queryset.by_wallet(wallet)
            logger.debug(f"Calculating statistics for wallet {wallet.id}")
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
            logger.debug(f"Calculating statistics for date range: {start_date} to {end_date}")
        
        # Aggregate statistics
        stats = queryset.aggregate(
            total_count=Count('id'),
            successful_count=Count('id', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
            pending_count=Count('id', filter=Q(status=TRANSACTION_STATUS_PENDING)),
            failed_count=Count('id', filter=Q(status=TRANSACTION_STATUS_FAILED)),
            total_amount=Sum('amount', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
            average_amount=Avg('amount', filter=Q(status=TRANSACTION_STATUS_SUCCESS)),
            total_fees=Sum('fees', filter=Q(status=TRANSACTION_STATUS_SUCCESS))
        )
        
        # Get counts by type
        type_stats = {}
        for txn_type, _ in TRANSACTION_TYPES:
            count = queryset.filter(
                transaction_type=txn_type,
                status=TRANSACTION_STATUS_SUCCESS
            ).count()
            type_stats[txn_type] = count
        
        stats['by_type'] = type_stats
        
        logger.info(f"Calculated transaction statistics: {stats}")
        
        return stats
    
    def get_transaction_summary(
        self,
        wallet: Optional[Wallet] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Get a summary of transactions grouped by type and status
        
        Args:
            wallet: Filter by wallet (optional)
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            dict: Transaction summary grouped by type and status
        """
        queryset = Transaction.objects.all()
        
        if wallet:
            queryset = queryset.by_wallet(wallet)
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        summary = {
            'by_type': {},
            'by_status': {},
            'overview': {}
        }
        
        # Summary by type
        for txn_type, type_display in TRANSACTION_TYPES:
            type_queryset = queryset.filter(transaction_type=txn_type)
            summary['by_type'][txn_type] = {
                'count': type_queryset.count(),
                'total_amount': type_queryset.filter(
                    status=TRANSACTION_STATUS_SUCCESS
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'display': type_display
            }
        
        # Summary by status
        for status, status_display in TRANSACTION_STATUSES:
            status_queryset = queryset.filter(status=status)
            summary['by_status'][status] = {
                'count': status_queryset.count(),
                'total_amount': status_queryset.aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0'),
                'display': status_display
            }
        
        # Overview
        summary['overview'] = {
            'total_transactions': queryset.count(),
            'total_value': queryset.filter(
                status=TRANSACTION_STATUS_SUCCESS
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            'total_fees': queryset.filter(
                status=TRANSACTION_STATUS_SUCCESS
            ).aggregate(total=Sum('fees'))['total'] or Decimal('0')
        }
        
        logger.info(f"Generated transaction summary")
        
        return summary
    
    # ==========================================
    # BULK OPERATIONS
    # ==========================================
    
    @db_transaction.atomic
    def bulk_update_status(
        self,
        transaction_ids: List[Any],
        status: str,
        reason: Optional[str] = None
    ) -> int:
        """
        Bulk update transaction statuses
        
        Args:
            transaction_ids: List of transaction IDs
            status: New status to set
            reason: Reason for status change (optional)
            
        Returns:
            int: Number of transactions updated
        """
        update_fields = {'status': status, 'updated_at': timezone.now()}
        
        if status in [TRANSACTION_STATUS_FAILED, TRANSACTION_STATUS_CANCELLED]:
            update_fields['failed_reason'] = reason or _("Bulk status update")
            update_fields['completed_at'] = timezone.now()
        elif status == TRANSACTION_STATUS_SUCCESS:
            update_fields['completed_at'] = timezone.now()
        
        updated_count = Transaction.objects.filter(
            id__in=transaction_ids
        ).update(**update_fields)
        
        logger.info(
            f"Bulk updated {updated_count} transactions to status {status}"
        )
        
        return updated_count