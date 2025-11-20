"""
Django Paystack Wallet - Settlement Service
Comprehensive business logic layer with atomic transactions and logging
"""
import logging
from decimal import Decimal
from typing import Optional, Dict, Any
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ObjectDoesNotExist
from djmoney.money import Money

from wallet.models import (
    Settlement,
    SettlementSchedule,
    Wallet,
    BankAccount,
    Transaction
)
from wallet.constants import (
    SETTLEMENT_STATUS_PENDING,
    SETTLEMENT_STATUS_PROCESSING,
    SETTLEMENT_STATUS_SUCCESS,
    SETTLEMENT_STATUS_FAILED,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED
)
from wallet.exceptions import (
    SettlementError,
    InsufficientFunds,
    InvalidAmount,
    WalletLocked
)
from wallet.services.paystack_service import PaystackService
from wallet.settings import get_wallet_setting


logger = logging.getLogger(__name__)


class SettlementService:
    """
    Service for handling wallet settlements
    
    This service provides comprehensive settlement management including:
    - Settlement creation and processing
    - Paystack integration
    - Webhook processing
    - Settlement schedules
    - Settlement verification
    """
    
    def __init__(self):
        """Initialize settlement service with Paystack integration"""
        self.paystack = PaystackService()
        logger.debug("SettlementService initialized")
    
    # ==========================================
    # SETTLEMENT RETRIEVAL
    # ==========================================
    
    def get_settlement(self, settlement_id: str) -> Settlement:
        """
        Get a settlement by ID
        
        Args:
            settlement_id: Settlement ID
            
        Returns:
            Settlement: Settlement object
            
        Raises:
            ObjectDoesNotExist: If settlement not found
        """
        try:
            settlement = Settlement.objects.with_full_details().get(id=settlement_id)
            logger.debug(f"Retrieved settlement {settlement_id}")
            return settlement
        except ObjectDoesNotExist:
            logger.error(f"Settlement {settlement_id} not found")
            raise
    
    def get_settlement_by_reference(self, reference: str) -> Settlement:
        """
        Get a settlement by reference
        
        Args:
            reference: Settlement reference
            
        Returns:
            Settlement: Settlement object
            
        Raises:
            ObjectDoesNotExist: If settlement not found
        """
        try:
            settlement = Settlement.objects.with_full_details().by_reference(reference)
            logger.debug(f"Retrieved settlement by reference: {reference}")
            return settlement
        except ObjectDoesNotExist:
            logger.error(f"Settlement with reference {reference} not found")
            raise
    
    def list_settlements(
        self,
        wallet: Optional[Wallet] = None,
        status: Optional[str] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ):
        """
        List settlements with optional filtering
        
        Args:
            wallet: Filter by wallet (optional)
            status: Filter by status (optional)
            start_date: Filter by start date (optional)
            end_date: Filter by end date (optional)
            min_amount: Filter by minimum amount (optional)
            max_amount: Filter by maximum amount (optional)
            limit: Limit number of results (optional)
            offset: Offset for pagination (optional)
            
        Returns:
            QuerySet: Filtered settlements
        """
        queryset = Settlement.objects.with_full_details()
        
        if wallet:
            queryset = queryset.by_wallet(wallet)
            logger.debug(f"Filtering settlements for wallet {wallet.id}")
        
        if status:
            queryset = queryset.filter(status=status)
            logger.debug(f"Filtering settlements by status: {status}")
        
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
            logger.debug(f"Filtering settlements by date range: {start_date} to {end_date}")
        
        if min_amount is not None or max_amount is not None:
            queryset = queryset.by_amount_range(min_amount, max_amount)
            logger.debug(f"Filtering settlements by amount range: {min_amount} to {max_amount}")
        
        # Order by most recent first
        queryset = queryset.order_by('-created_at')
        
        # Apply pagination
        if offset is not None:
            queryset = queryset[offset:]
        if limit is not None:
            queryset = queryset[:limit]
        
        return queryset
    
    # ==========================================
    # SETTLEMENT CREATION
    # ==========================================
    
    @db_transaction.atomic
    def create_settlement(
        self,
        wallet: Wallet,
        bank_account: BankAccount,
        amount: Money,
        reason: Optional[str] = None,
        metadata: Optional[Dict] = None,
        auto_process: bool = True
    ) -> Settlement:
        """
        Create a new settlement
        
        Args:
            wallet: Wallet to settle from
            bank_account: Bank account to settle to
            amount: Amount to settle (Money object)
            reason: Reason for settlement (optional)
            metadata: Additional metadata (optional)
            auto_process: Automatically process the settlement (default: True)
            
        Returns:
            Settlement: Created settlement object
            
        Raises:
            WalletLocked: If wallet is locked
            InsufficientFunds: If wallet has insufficient funds
            InvalidAmount: If amount is invalid
            SettlementError: If settlement creation fails
        """
        logger.info(
            f"Creating settlement: wallet={wallet.id}, "
            f"bank_account={bank_account.id}, amount={amount}"
        )
        
        # Validate wallet is not locked
        if wallet.is_locked:
            logger.error(f"Wallet {wallet.id} is locked")
            raise WalletLocked(wallet)
        
        # Validate amount is positive
        if amount.amount <= 0:
            logger.error(f"Invalid amount: {amount}")
            raise InvalidAmount(_("Amount must be greater than zero"))
        
        # Validate sufficient funds
        if wallet.balance.amount < amount.amount:
            logger.error(
                f"Insufficient funds in wallet {wallet.id}: "
                f"balance={wallet.balance.amount}, required={amount.amount}"
            )
            raise InsufficientFunds(wallet, amount.amount)
        
        # Validate minimum balance requirement
        minimum_balance = Money(
            get_wallet_setting('MINIMUM_BALANCE'),
            wallet.balance.currency
        )
        
        if wallet.balance.amount - amount.amount < minimum_balance.amount:
            logger.error(
                f"Settlement would leave wallet {wallet.id} below minimum balance"
            )
            raise SettlementError(
                _("Settlement would leave wallet below minimum balance of %(min)s") % {
                    'min': minimum_balance
                }
            )
        
        # Generate reference
        from wallet.utils.id_generators import generate_settlement_reference
        reference = generate_settlement_reference()
        
        logger.debug(f"Generated settlement reference: {reference}")
        
        try:
            # Deduct amount from wallet first
            wallet.withdraw(amount.amount)
            logger.info(f"Deducted {amount} from wallet {wallet.id}")
            
            # Create settlement record
            settlement = Settlement.objects.create(
                wallet=wallet,
                bank_account=bank_account,
                amount=amount,
                status=SETTLEMENT_STATUS_PENDING,
                reference=reference,
                reason=reason or _("Settlement to bank account"),
                metadata=metadata or {}
            )
            
            logger.info(f"Created settlement {settlement.id} with reference {reference}")
            
            # Create transaction for the settlement
            transaction_obj = Transaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
                status=TRANSACTION_STATUS_SUCCESS,
                description=reason or _("Settlement to bank account"),
                reference=f"STL-{settlement.reference}",
                recipient_bank_account=bank_account,
                metadata={
                    'settlement_id': str(settlement.id),
                    'settlement_reference': settlement.reference
                }
            )
            
            logger.info(
                f"Created transaction {transaction_obj.id} for settlement {settlement.id}"
            )
            
            # Link transaction to settlement
            settlement.transaction = transaction_obj
            settlement.save(update_fields=['transaction'])
            
            # Process the settlement if auto_process is True
            if auto_process:
                logger.debug(f"Auto-processing settlement {settlement.id}")
                self.process_settlement(settlement)
            
            return settlement
            
        except Exception as e:
            logger.error(
                f"Error creating settlement: {str(e)}",
                exc_info=True
            )
            
            # Refund wallet if settlement creation failed
            try:
                wallet.deposit(amount.amount)
                logger.info(f"Refunded {amount} to wallet {wallet.id} after failed settlement")
            except Exception as refund_error:
                logger.error(
                    f"Error refunding wallet after failed settlement: {str(refund_error)}",
                    exc_info=True
                )
            
            raise SettlementError(str(e)) from e
    
    # ==========================================
    # SETTLEMENT PROCESSING
    # ==========================================
    
    @db_transaction.atomic
    def process_settlement(self, settlement: Settlement) -> Settlement:
        """
        Process a pending settlement
        
        Args:
            settlement: Settlement to process
            
        Returns:
            Settlement: Updated settlement
            
        Raises:
            SettlementError: If settlement processing fails
        """
        logger.info(f"Processing settlement {settlement.id}")
        
        # Verify settlement is in pending status
        if settlement.status != SETTLEMENT_STATUS_PENDING:
            logger.warning(
                f"Settlement {settlement.id} is not pending (status: {settlement.status})"
            )
            raise SettlementError(
                _("Only pending settlements can be processed")
            )
        
        # Mark as processing
        settlement.mark_as_processing()
        logger.info(f"Settlement {settlement.id} marked as processing")
        
        try:
            # Convert amount to kobo/cents (Paystack uses minor currency units)
            amount_in_minor_unit = int(settlement.amount.amount * 100)
            
            logger.debug(
                f"Initiating Paystack transfer: amount={amount_in_minor_unit}, "
                f"recipient={settlement.bank_account.paystack_recipient_code}"
            )
            
            # Create bank transfer using Paystack
            transfer_data = self.paystack.initiate_transfer(
                amount=amount_in_minor_unit,
                recipient_code=settlement.bank_account.paystack_recipient_code,
                reference=settlement.reference,
                reason=settlement.reason or _("Settlement to bank account")
            )
            
            logger.info(
                f"Paystack transfer initiated for settlement {settlement.id}: "
                f"transfer_code={transfer_data.get('transfer_code')}"
            )
            
            # Update settlement with Paystack data
            settlement.paystack_transfer_code = transfer_data.get('transfer_code')
            settlement.paystack_transfer_data = transfer_data
            
            # Update status based on Paystack response
            paystack_status = transfer_data.get('status')
            
            if paystack_status == 'success':
                settlement.mark_as_success(transfer_data)
                logger.info(f"Settlement {settlement.id} marked as successful")
            else:
                # Still pending, will be updated by webhook
                settlement.status = SETTLEMENT_STATUS_PENDING
                settlement.save(update_fields=['paystack_transfer_code', 'paystack_transfer_data', 'status'])
                logger.info(
                    f"Settlement {settlement.id} pending Paystack confirmation"
                )
            
            return settlement
            
        except Exception as e:
            logger.error(
                f"Error processing settlement {settlement.id}: {str(e)}",
                exc_info=True
            )
            
            # Mark settlement as failed
            settlement.mark_as_failed(str(e))
            
            # Refund wallet
            try:
                settlement.wallet.deposit(settlement.amount.amount)
                logger.info(
                    f"Refunded {settlement.amount} to wallet {settlement.wallet.id} "
                    f"after failed settlement"
                )
            except Exception as refund_error:
                logger.error(
                    f"Error refunding wallet after failed settlement: {str(refund_error)}",
                    exc_info=True
                )
            
            # Re-raise with more context
            raise SettlementError(
                f"Settlement processing failed: {str(e)}",
                settlement.reference
            ) from e
    
    # ==========================================
    # SETTLEMENT VERIFICATION
    # ==========================================
    
    def verify_settlement(self, settlement: Settlement) -> Settlement:
        """
        Verify a settlement's status with Paystack
        
        Args:
            settlement: Settlement to verify
            
        Returns:
            Settlement: Updated settlement
            
        Raises:
            SettlementError: If settlement doesn't have transfer code
        """
        logger.info(f"Verifying settlement {settlement.id}")
        
        if not settlement.paystack_transfer_code:
            logger.error(
                f"Settlement {settlement.id} does not have a Paystack transfer code"
            )
            raise SettlementError(
                _("Settlement does not have a Paystack transfer code")
            )
        
        try:
            # Get settlement status from Paystack
            transfer_data = self.paystack.verify_transfer(settlement.reference)
            
            logger.debug(
                f"Paystack verification response for settlement {settlement.id}: "
                f"status={transfer_data.get('status')}"
            )
            
            # Update settlement with latest data
            settlement.paystack_transfer_data = transfer_data
            
            # Update status based on Paystack status
            paystack_status = transfer_data.get('status')
            
            if paystack_status == 'success':
                settlement.mark_as_success(transfer_data)
                logger.info(f"Settlement {settlement.id} verified as successful")
            elif paystack_status == 'failed':
                settlement.mark_as_failed(
                    transfer_data.get('reason'),
                    transfer_data
                )
                logger.warning(
                    f"Settlement {settlement.id} verified as failed: "
                    f"{transfer_data.get('reason')}"
                )
            else:
                settlement.save(update_fields=['paystack_transfer_data'])
                logger.info(
                    f"Settlement {settlement.id} still in status: {paystack_status}"
                )
            
            return settlement
            
        except Exception as e:
            logger.error(
                f"Error verifying settlement {settlement.id}: {str(e)}",
                exc_info=True
            )
            # Don't change settlement status based on verification error
            return settlement
    
    # ==========================================
    # SETTLEMENT RETRY
    # ==========================================
    
    @db_transaction.atomic
    def retry_settlement(self, settlement: Settlement) -> Settlement:
        """
        Retry a failed settlement
        
        Args:
            settlement: Settlement to retry
            
        Returns:
            Settlement: Updated settlement
            
        Raises:
            SettlementError: If settlement cannot be retried
        """
        logger.info(f"Retrying settlement {settlement.id}")
        
        # Verify settlement is in failed status
        if settlement.status != SETTLEMENT_STATUS_FAILED:
            logger.warning(
                f"Settlement {settlement.id} is not failed (status: {settlement.status})"
            )
            raise SettlementError(
                _("Only failed settlements can be retried")
            )
        
        # Check if wallet has sufficient funds (in case it was refunded)
        if settlement.wallet.balance.amount < settlement.amount.amount:
            logger.error(
                f"Insufficient funds in wallet {settlement.wallet.id} for retry"
            )
            raise InsufficientFunds(settlement.wallet, settlement.amount.amount)
        
        # Reset settlement status to pending
        settlement.status = SETTLEMENT_STATUS_PENDING
        settlement.failure_reason = None
        settlement.save(update_fields=['status', 'failure_reason'])
        
        logger.info(f"Settlement {settlement.id} reset to pending status")
        
        # Process the settlement again
        return self.process_settlement(settlement)
    
    # ==========================================
    # WEBHOOK PROCESSING
    # ==========================================
    
    def process_paystack_webhook(self, event_type: str, data: Dict) -> bool:
        """
        Process a Paystack webhook event related to settlements
        
        Args:
            event_type: Webhook event type
            data: Webhook event data
            
        Returns:
            bool: True if processed successfully
        """
        logger.info(f"Processing webhook event: {event_type}")
        
        # Handle transfer.success event
        if event_type == 'transfer.success':
            return self._process_transfer_success(data)
        
        # Handle transfer.failed event
        elif event_type == 'transfer.failed':
            return self._process_transfer_failed(data)
        
        # Handle transfer.reversed event
        elif event_type == 'transfer.reversed':
            return self._process_transfer_reversed(data)
        
        # Not a relevant event
        logger.debug(f"Event type {event_type} not relevant to settlements")
        return False
    
    @db_transaction.atomic
    def _process_transfer_success(self, data: Dict) -> bool:
        """
        Process transfer.success webhook event for settlements
        
        Args:
            data: Webhook event data
            
        Returns:
            bool: True if processed successfully
        """
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        
        logger.info(
            f"Processing transfer.success: reference={reference}, "
            f"transfer_code={transfer_code}"
        )
        
        # Find settlement by reference or transfer code
        settlement = None
        
        try:
            if reference:
                settlement = Settlement.objects.filter(reference=reference).first()
            
            if not settlement and transfer_code:
                settlement = Settlement.objects.filter(
                    paystack_transfer_code=transfer_code
                ).first()
        except Exception as e:
            logger.error(f"Error finding settlement: {str(e)}", exc_info=True)
            return False
        
        if settlement:
            logger.info(f"Found settlement {settlement.id} for successful transfer")
            
            # Update settlement status
            settlement.mark_as_success(data)
            
            logger.info(f"Settlement {settlement.id} marked as successful via webhook")
            return True
        else:
            logger.warning(
                f"No settlement found for reference={reference}, "
                f"transfer_code={transfer_code}"
            )
        
        return False
    
    @db_transaction.atomic
    def _process_transfer_failed(self, data: Dict) -> bool:
        """
        Process transfer.failed webhook event for settlements
        
        Args:
            data: Webhook event data
            
        Returns:
            bool: True if processed successfully
        """
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason', _("Transfer failed"))
        
        logger.info(
            f"Processing transfer.failed: reference={reference}, "
            f"transfer_code={transfer_code}, reason={reason}"
        )
        
        # Find settlement by reference or transfer code
        settlement = None
        
        try:
            if reference:
                settlement = Settlement.objects.filter(reference=reference).first()
            
            if not settlement and transfer_code:
                settlement = Settlement.objects.filter(
                    paystack_transfer_code=transfer_code
                ).first()
        except Exception as e:
            logger.error(f"Error finding settlement: {str(e)}", exc_info=True)
            return False
        
        if settlement:
            logger.info(f"Found settlement {settlement.id} for failed transfer")
            
            # Update settlement status
            settlement.mark_as_failed(reason, data)
            
            # Refund the wallet
            try:
                settlement.wallet.deposit(settlement.amount.amount)
                logger.info(
                    f"Refunded {settlement.amount} to wallet {settlement.wallet.id} "
                    f"after failed transfer"
                )
                
                # Update transaction status
                if settlement.transaction:
                    settlement.transaction.status = TRANSACTION_STATUS_FAILED
                    settlement.transaction.failed_reason = reason
                    settlement.transaction.save(
                        update_fields=['status', 'failed_reason']
                    )
                    logger.info(
                        f"Transaction {settlement.transaction.id} marked as failed"
                    )
            except Exception as e:
                logger.error(
                    f"Error refunding wallet after failed settlement {settlement.reference}: "
                    f"{str(e)}",
                    exc_info=True
                )
            
            logger.info(f"Settlement {settlement.id} marked as failed via webhook")
            return True
        else:
            logger.warning(
                f"No settlement found for reference={reference}, "
                f"transfer_code={transfer_code}"
            )
        
        return False
    
    @db_transaction.atomic
    def _process_transfer_reversed(self, data: Dict) -> bool:
        """
        Process transfer.reversed webhook event for settlements
        
        Args:
            data: Webhook event data
            
        Returns:
            bool: True if processed successfully
        """
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason', _("Transfer reversed"))
        
        logger.info(
            f"Processing transfer.reversed: reference={reference}, "
            f"transfer_code={transfer_code}, reason={reason}"
        )
        
        # Find settlement by reference or transfer code
        settlement = None
        
        try:
            if reference:
                settlement = Settlement.objects.filter(reference=reference).first()
            
            if not settlement and transfer_code:
                settlement = Settlement.objects.filter(
                    paystack_transfer_code=transfer_code
                ).first()
        except Exception as e:
            logger.error(f"Error finding settlement: {str(e)}", exc_info=True)
            return False
        
        if settlement:
            logger.info(f"Found settlement {settlement.id} for reversed transfer")
            
            # Update settlement status
            settlement.mark_as_failed(reason, data)
            
            # Refund the wallet
            try:
                settlement.wallet.deposit(settlement.amount.amount)
                logger.info(
                    f"Refunded {settlement.amount} to wallet {settlement.wallet.id} "
                    f"after reversed transfer"
                )
                
                # Update transaction status
                if settlement.transaction:
                    settlement.transaction.status = 'reversed'
                    settlement.transaction.failed_reason = reason
                    settlement.transaction.save(
                        update_fields=['status', 'failed_reason']
                    )
                    logger.info(
                        f"Transaction {settlement.transaction.id} marked as reversed"
                    )
            except Exception as e:
                logger.error(
                    f"Error refunding wallet after reversed settlement {settlement.reference}: "
                    f"{str(e)}",
                    exc_info=True
                )
            
            logger.info(f"Settlement {settlement.id} marked as reversed via webhook")
            return True
        else:
            logger.warning(
                f"No settlement found for reference={reference}, "
                f"transfer_code={transfer_code}"
            )
        
        return False
    
    # ==========================================
    # SETTLEMENT SCHEDULES
    # ==========================================
    
    @db_transaction.atomic
    def create_settlement_schedule(
        self,
        wallet: Wallet,
        bank_account: BankAccount,
        schedule_type: str,
        amount_threshold: Optional[Money] = None,
        minimum_amount: Optional[Money] = None,
        maximum_amount: Optional[Money] = None,
        day_of_week: Optional[int] = None,
        day_of_month: Optional[int] = None,
        time_of_day: Optional[Any] = None
    ) -> SettlementSchedule:
        """
        Create a new settlement schedule
        
        Args:
            wallet: Wallet to schedule settlements for
            bank_account: Bank account to settle to
            schedule_type: Type of schedule (daily/weekly/monthly/threshold)
            amount_threshold: Threshold amount (for threshold schedules)
            minimum_amount: Minimum amount to settle
            maximum_amount: Maximum amount to settle
            day_of_week: Day of week (for weekly schedules)
            day_of_month: Day of month (for monthly schedules)
            time_of_day: Time of day for scheduled settlements
            
        Returns:
            SettlementSchedule: Created schedule object
        """
        logger.info(
            f"Creating settlement schedule: wallet={wallet.id}, "
            f"bank_account={bank_account.id}, type={schedule_type}"
        )
        
        # Create schedule
        schedule = SettlementSchedule.objects.create(
            wallet=wallet,
            bank_account=bank_account,
            schedule_type=schedule_type,
            amount_threshold=amount_threshold,
            minimum_amount=minimum_amount or Money(0, wallet.balance.currency),
            maximum_amount=maximum_amount,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            time_of_day=time_of_day
        )
        
        logger.info(f"Created settlement schedule {schedule.id}")
        
        return schedule
    
    def process_due_settlements(self) -> int:
        """
        Process all due scheduled settlements
        
        Returns:
            int: Number of settlements processed
        """
        logger.info("Processing due settlement schedules")
        
        now = timezone.now()
        count = 0
        
        # Get all active schedules with due next_settlement date
        due_schedules = SettlementSchedule.objects.due_now().with_full_details()
        
        logger.info(f"Found {due_schedules.count()} due schedules")
        
        for schedule in due_schedules:
            try:
                # Determine settlement amount
                amount = self._calculate_settlement_amount(schedule)
                
                # Check if amount is positive
                if amount.amount > 0:
                    logger.info(
                        f"Creating settlement for schedule {schedule.id}: "
                        f"amount={amount}"
                    )
                    
                    # Create settlement
                    self.create_settlement(
                        wallet=schedule.wallet,
                        bank_account=schedule.bank_account,
                        amount=amount,
                        reason=f"Scheduled {schedule.get_schedule_type_display()} settlement",
                        metadata={
                            'schedule_id': str(schedule.id),
                            'schedule_type': schedule.schedule_type
                        }
                    )
                    count += 1
                else:
                    logger.debug(
                        f"Schedule {schedule.id} skipped: calculated amount is {amount}"
                    )
                
                # Update schedule
                schedule.last_settlement = now
                schedule.calculate_next_settlement()
                schedule.save(update_fields=['last_settlement', 'next_settlement'])
                
            except Exception as e:
                logger.error(
                    f"Error processing scheduled settlement for {schedule.id}: {str(e)}",
                    exc_info=True
                )
        
        # Handle threshold-based schedules
        threshold_schedules = SettlementSchedule.objects.threshold_based().with_full_details()
        
        logger.info(f"Found {threshold_schedules.count()} threshold-based schedules")
        
        for schedule in threshold_schedules:
            try:
                # Check if balance exceeds threshold
                if schedule.wallet.balance >= schedule.amount_threshold:
                    logger.info(
                        f"Wallet {schedule.wallet.id} balance ({schedule.wallet.balance}) "
                        f"exceeds threshold ({schedule.amount_threshold})"
                    )
                    
                    # Determine settlement amount
                    amount = self._calculate_settlement_amount(schedule)
                    
                    # Check if amount is positive
                    if amount.amount > 0:
                        logger.info(
                            f"Creating threshold settlement for schedule {schedule.id}: "
                            f"amount={amount}"
                        )
                        
                        # Create settlement
                        self.create_settlement(
                            wallet=schedule.wallet,
                            bank_account=schedule.bank_account,
                            amount=amount,
                            reason=_("Threshold-based settlement"),
                            metadata={
                                'schedule_id': str(schedule.id),
                                'schedule_type': schedule.schedule_type,
                                'threshold': str(schedule.amount_threshold.amount)
                            }
                        )
                        count += 1
                        
                        # Update last settlement date
                        schedule.last_settlement = now
                        schedule.save(update_fields=['last_settlement'])
                    else:
                        logger.debug(
                            f"Schedule {schedule.id} skipped: calculated amount is {amount}"
                        )
            except Exception as e:
                logger.error(
                    f"Error processing threshold settlement for {schedule.id}: {str(e)}",
                    exc_info=True
                )
        
        logger.info(f"Processed {count} scheduled settlements")
        return count
    
    def _calculate_settlement_amount(self, schedule: SettlementSchedule) -> Money:
        """
        Calculate the settlement amount for a given schedule
        
        Args:
            schedule: The settlement schedule
            
        Returns:
            Money: The amount to settle
        """
        wallet_balance = schedule.wallet.balance
        
        # Apply minimum balance retention if configured
        minimum_balance = Money(
            get_wallet_setting('MINIMUM_BALANCE'),
            wallet_balance.currency
        )
        
        available_balance = max(
            Money(0, wallet_balance.currency),
            wallet_balance - minimum_balance
        )
        
        logger.debug(
            f"Calculating settlement amount for schedule {schedule.id}: "
            f"wallet_balance={wallet_balance}, available={available_balance}"
        )
        
        # Apply minimum settlement amount
        if available_balance < schedule.minimum_amount:
            logger.debug(
                f"Available balance ({available_balance}) below minimum ({schedule.minimum_amount})"
            )
            return Money(0, wallet_balance.currency)
        
        # Apply maximum settlement amount if configured
        if schedule.maximum_amount is not None and available_balance > schedule.maximum_amount:
            logger.debug(
                f"Available balance ({available_balance}) capped at maximum ({schedule.maximum_amount})"
            )
            return schedule.maximum_amount
        
        logger.debug(f"Settlement amount calculated: {available_balance}")
        return available_balance
    
    # ==========================================
    # SETTLEMENT STATISTICS
    # ==========================================
    
    def get_settlement_statistics(
        self,
        wallet: Optional[Wallet] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None
    ) -> Dict:
        """
        Get settlement statistics
        
        Args:
            wallet: Filter by wallet (optional)
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            dict: Settlement statistics
        """
        logger.debug("Calculating settlement statistics")
        
        stats = Settlement.objects.statistics(wallet, start_date, end_date)
        
        logger.info(f"Settlement statistics: {stats}")
        
        return stats