import logging
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from wallet.models import Transaction, Wallet
from wallet.constants import (
    TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_SUCCESS, 
    TRANSACTION_STATUS_FAILED, TRANSACTION_STATUS_CANCELLED,
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_TYPE_WITHDRAWAL, 
    TRANSACTION_TYPE_TRANSFER, TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_REFUND, TRANSACTION_TYPE_REVERSAL
)
from wallet.exceptions import TransactionFailed
from wallet.settings import get_wallet_setting


logger = logging.getLogger(__name__)


class TransactionService:
    """
    Service for transaction operations
    """
    def get_transaction(self, transaction_id, for_update=False):
        """
        Get a transaction by ID
        
        Args:
            transaction_id: Transaction ID
            for_update (bool): Whether to lock the transaction for update
            
        Returns:
            Transaction: Transaction object
        """
        queryset = Transaction.objects.all()
        
        if for_update:
            queryset = queryset.select_for_update()
        
        return queryset.get(id=transaction_id)
    
    def get_transaction_by_reference(self, reference, for_update=False):
        """
        Get a transaction by reference
        
        Args:
            reference (str): Transaction reference
            for_update (bool): Whether to lock the transaction for update
            
        Returns:
            Transaction: Transaction object
        """
        queryset = Transaction.objects.all()
        
        if for_update:
            queryset = queryset.select_for_update()
        
        return queryset.get(reference=reference)
    
    def list_transactions(self, wallet=None, status=None, transaction_type=None, 
                          start_date=None, end_date=None, limit=None, offset=None):
        """
        List transactions with optional filtering
        
        Args:
            wallet (Wallet, optional): Filter by wallet
            status (str, optional): Filter by status
            transaction_type (str, optional): Filter by transaction type
            start_date (datetime, optional): Filter by start date
            end_date (datetime, optional): Filter by end date
            limit (int, optional): Limit number of results
            offset (int, optional): Offset for pagination
            
        Returns:
            QuerySet: Filtered transactions
        """
        queryset = Transaction.objects.all()
        
        if wallet:
            queryset = queryset.filter(wallet=wallet)
            
        if status:
            queryset = queryset.filter(status=status)
            
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
            
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
            
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        queryset = queryset.order_by('-created_at')
        
        if offset is not None:
            queryset = queryset[offset:]
            
        if limit is not None:
            queryset = queryset[:limit]
            
        return queryset
    
    def create_transaction(self, wallet, amount, transaction_type, status=TRANSACTION_STATUS_PENDING, 
                          description=None, metadata=None, reference=None, **kwargs):
        """
        Create a new transaction
        
        Args:
            wallet (Wallet): Wallet for the transaction
            amount (Decimal): Transaction amount
            transaction_type (str): Type of transaction
            status (str, optional): Transaction status
            description (str, optional): Description of the transaction
            metadata (dict, optional): Additional metadata
            reference (str, optional): Transaction reference
            **kwargs: Additional fields for the transaction
            
        Returns:
            Transaction: Created transaction
        """
        if reference is None:
            from wallet.utils.id_generators import generate_transaction_reference
            reference = generate_transaction_reference()
            
        return Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=transaction_type,
            status=status,
            description=description,
            metadata=metadata or {},
            reference=reference,
            **kwargs
        )
    
    @transaction.atomic
    def mark_transaction_as_success(self, transaction, paystack_data=None):
        """
        Mark a transaction as successful
        
        Args:
            transaction (Transaction): Transaction to update
            paystack_data (dict, optional): Paystack response data
            
        Returns:
            Transaction: Updated transaction
        """
        transaction = self.get_transaction(transaction.id, for_update=True)
        
        if transaction.status == TRANSACTION_STATUS_SUCCESS:
            return transaction
        
        # Update transaction
        transaction.status = TRANSACTION_STATUS_SUCCESS
        transaction.completed_at = timezone.now()
        
        if paystack_data:
            transaction.paystack_response = paystack_data
            
            if 'reference' in paystack_data:
                transaction.paystack_reference = paystack_data['reference']
        
        transaction.save()
        
        # Perform actions based on transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_DEPOSIT:
            # Credit the wallet
            if not transaction.wallet.balance.amount >= transaction.amount.amount:
                transaction.wallet.deposit(transaction.amount.amount)
        
        return transaction
    
    @transaction.atomic
    def mark_transaction_as_failed(self, transaction, reason=None, paystack_data=None):
        """
        Mark a transaction as failed
        
        Args:
            transaction (Transaction): Transaction to update
            reason (str, optional): Reason for failure
            paystack_data (dict, optional): Paystack response data
            
        Returns:
            Transaction: Updated transaction
        """
        transaction = self.get_transaction(transaction.id, for_update=True)
        
        if transaction.status == TRANSACTION_STATUS_FAILED:
            return transaction
        
        # Update transaction
        transaction.status = TRANSACTION_STATUS_FAILED
        transaction.failed_reason = reason or _("Transaction failed")
        
        if paystack_data:
            transaction.paystack_response = paystack_data
        
        transaction.save()
        
        # Perform actions based on transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            # Refund the wallet
            transaction.wallet.deposit(transaction.amount.amount)
        
        return transaction
    
    @transaction.atomic
    def cancel_transaction(self, transaction, reason=None):
        """
        Cancel a pending transaction
        
        Args:
            transaction (Transaction): Transaction to cancel
            reason (str, optional): Reason for cancellation
            
        Returns:
            Transaction: Updated transaction
            
        Raises:
            ValueError: If transaction is not in pending status
        """
        transaction = self.get_transaction(transaction.id, for_update=True)
        
        if transaction.status != TRANSACTION_STATUS_PENDING:
            raise ValueError(_("Only pending transactions can be cancelled"))
        
        # Update transaction
        transaction.status = TRANSACTION_STATUS_CANCELLED
        transaction.failed_reason = reason or _("Transaction cancelled")
        transaction.save()
        
        # Perform actions based on transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            # Refund the wallet
            transaction.wallet.deposit(transaction.amount.amount)
        
        return transaction
    
    @transaction.atomic
    def refund_transaction(self, transaction, amount=None, reason=None):
        """
        Create a refund for a transaction
        
        Args:
            transaction (Transaction): Transaction to refund
            amount (Decimal, optional): Amount to refund, defaults to full amount
            reason (str, optional): Reason for refund
            
        Returns:
            Transaction: Refund transaction
            
        Raises:
            ValueError: If transaction cannot be refunded
        """
        transaction = self.get_transaction(transaction.id)
        
        if transaction.status != TRANSACTION_STATUS_SUCCESS:
            raise ValueError(_("Only successful transactions can be refunded"))
        
        if transaction.transaction_type not in [TRANSACTION_TYPE_PAYMENT, TRANSACTION_TYPE_DEPOSIT]:
            raise ValueError(_("Only payment and deposit transactions can be refunded"))
        
        # Determine refund amount
        if amount is None:
            amount = transaction.amount.amount
        else:
            amount = Decimal(str(amount))
            
            if amount > transaction.amount.amount:
                raise ValueError(_("Refund amount cannot exceed original transaction amount"))
        
        # Create refund transaction
        refund_transaction = self.create_transaction(
            wallet=transaction.wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_REFUND,
            status=TRANSACTION_STATUS_PENDING,
            description=reason or _("Refund for transaction {reference}").format(reference=transaction.reference),
            related_transaction=transaction
        )
        
        # Process refund
        if transaction.transaction_type == TRANSACTION_TYPE_PAYMENT:
            # Credit the wallet
            transaction.wallet.deposit(amount)
            
            # Update refund transaction
            refund_transaction.status = TRANSACTION_STATUS_SUCCESS
            refund_transaction.completed_at = timezone.now()
            refund_transaction.save()
        
        return refund_transaction
    
    @transaction.atomic
    def reverse_transaction(self, transaction, reason=None):
        """
        Create a reversal for a transaction
        
        Args:
            transaction (Transaction): Transaction to reverse
            reason (str, optional): Reason for reversal
            
        Returns:
            Transaction: Reversal transaction
            
        Raises:
            ValueError: If transaction cannot be reversed
        """
        transaction = self.get_transaction(transaction.id)
        
        if transaction.status != TRANSACTION_STATUS_SUCCESS:
            raise ValueError(_("Only successful transactions can be reversed"))
        
        # Create reversal transaction
        reversal_transaction = self.create_transaction(
            wallet=transaction.wallet,
            amount=transaction.amount.amount,
            transaction_type=TRANSACTION_TYPE_REVERSAL,
            status=TRANSACTION_STATUS_PENDING,
            description=reason or _("Reversal for transaction {reference}").format(reference=transaction.reference),
            related_transaction=transaction
        )
        
        # Process reversal based on original transaction type
        if transaction.transaction_type == TRANSACTION_TYPE_DEPOSIT:
            # Debit the wallet
            try:
                transaction.wallet.withdraw(transaction.amount.amount)
                
                # Update reversal transaction
                reversal_transaction.status = TRANSACTION_STATUS_SUCCESS
                reversal_transaction.completed_at = timezone.now()
                reversal_transaction.save()
            except Exception as e:
                # Mark reversal as failed
                reversal_transaction.status = TRANSACTION_STATUS_FAILED
                reversal_transaction.failed_reason = str(e)
                reversal_transaction.save()
                
                # Re-raise the exception
                raise
                
        elif transaction.transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            # Credit the wallet
            transaction.wallet.deposit(transaction.amount.amount)
            
            # Update reversal transaction
            reversal_transaction.status = TRANSACTION_STATUS_SUCCESS
            reversal_transaction.completed_at = timezone.now()
            reversal_transaction.save()
            
        elif transaction.transaction_type == TRANSACTION_TYPE_TRANSFER:
            # Handle transfer reversal (more complex)
            if transaction.recipient_wallet:
                try:
                    # Reverse the transfer
                    transaction.recipient_wallet.transfer(
                        transaction.wallet,
                        transaction.amount.amount,
                        _("Reversal of transfer {reference}").format(reference=transaction.reference)
                    )
                    
                    # Update reversal transaction
                    reversal_transaction.status = TRANSACTION_STATUS_SUCCESS
                    reversal_transaction.completed_at = timezone.now()
                    reversal_transaction.save()
                except Exception as e:
                    # Mark reversal as failed
                    reversal_transaction.status = TRANSACTION_STATUS_FAILED
                    reversal_transaction.failed_reason = str(e)
                    reversal_transaction.save()
                    
                    # Re-raise the exception
                    raise
            else:
                # Can't reverse if recipient wallet is unknown
                reversal_transaction.status = TRANSACTION_STATUS_FAILED
                reversal_transaction.failed_reason = _("Cannot reverse transfer: recipient wallet unknown")
                reversal_transaction.save()
                
                raise ValueError(_("Cannot reverse transfer: recipient wallet unknown"))
        
        return reversal_transaction
    
    def verify_paystack_transaction(self, reference):
        """
        Verify a Paystack transaction by reference
        
        Args:
            reference (str): Transaction reference
            
        Returns:
            dict: Verification data
        """
        from wallet.services.paystack_service import PaystackService
        
        paystack = PaystackService()
        return paystack.verify_transaction(reference)
    
    @transaction.atomic
    def process_paystack_webhook(self, event_type, data):
        """
        Process a Paystack webhook event
        
        Args:
            event_type (str): Webhook event type
            data (dict): Webhook event data
            
        Returns:
            bool: True if processed successfully
        """
        # Handle charge.success event
        if event_type == 'charge.success':
            return self._process_charge_success(data)
            
        # Handle transfer.success event
        elif event_type == 'transfer.success':
            return self._process_transfer_success(data)
            
        # Handle transfer.failed event
        elif event_type == 'transfer.failed':
            return self._process_transfer_failed(data)
            
        # Handle transfer.reversed event
        elif event_type == 'transfer.reversed':
            return self._process_transfer_reversed(data)
            
        # Unknown event type
        logger.warning(f"Unknown Paystack webhook event type: {event_type}")
        return False
    
    def _process_charge_success(self, data):
        """Process charge.success webhook event"""
        reference = data.get('reference')
        
        # Find transaction by reference
        try:
            transaction = Transaction.objects.get(paystack_reference=reference)
            
            # Update transaction status
            return self.mark_transaction_as_success(transaction, data)
        except Transaction.DoesNotExist:
            # Transaction not found, might be a new deposit
            # Extract metadata
            metadata = data.get('metadata', {})
            wallet_id = metadata.get('wallet_id')
            
            if wallet_id:
                try:
                    # Get the wallet
                    wallet = Wallet.objects.get(id=wallet_id)
                    
                    # Process the charge
                    from wallet.services.wallet_service import WalletService
                    wallet_service = WalletService()
                    wallet_service.process_successful_card_charge(data)
                    
                    return True
                except Wallet.DoesNotExist:
                    logger.error(f"Wallet not found for charge success: {wallet_id}")
                except Exception as e:
                    logger.error(f"Error processing charge success: {str(e)}")
            
            logger.warning(f"Transaction not found for charge success: {reference}")
            return False
    
    def _process_transfer_success(self, data):
        """Process transfer.success webhook event"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        
        # Find transaction by reference or transfer code
        try:
            transaction = Transaction.objects.filter(
                paystack_reference__in=[reference, transfer_code]
            ).first()
            
            if transaction:
                # Update transaction status
                return self.mark_transaction_as_success(transaction, data)
            else:
                logger.warning(f"Transaction not found for transfer success: {reference} / {transfer_code}")
                return False
        except Exception as e:
            logger.error(f"Error processing transfer success: {str(e)}")
            return False
    
    def _process_transfer_failed(self, data):
        """Process transfer.failed webhook event"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason')
        
        # Find transaction by reference or transfer code
        try:
            transaction = Transaction.objects.filter(
                paystack_reference__in=[reference, transfer_code]
            ).first()
            
            if transaction:
                # Update transaction status
                return self.mark_transaction_as_failed(transaction, reason, data)
            else:
                logger.warning(f"Transaction not found for transfer failed: {reference} / {transfer_code}")
                return False
        except Exception as e:
            logger.error(f"Error processing transfer failed: {str(e)}")
            return False
    
    def _process_transfer_reversed(self, data):
        """Process transfer.reversed webhook event"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason')
        
        # Find transaction by reference or transfer code
        try:
            transaction = Transaction.objects.filter(
                paystack_reference__in=[reference, transfer_code]
            ).first()
            
            if transaction:
                # Create a reversal transaction
                self.reverse_transaction(transaction, reason)
                return True
            else:
                logger.warning(f"Transaction not found for transfer reversed: {reference} / {transfer_code}")
                return False
        except Exception as e:
            logger.error(f"Error processing transfer reversed: {str(e)}")
            return False