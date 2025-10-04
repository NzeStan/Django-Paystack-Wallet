import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money
from django.core.exceptions import ObjectDoesNotExist
from wallet.models import Settlement, SettlementSchedule, Wallet, BankAccount, Transaction
from wallet.constants import (
    SETTLEMENT_STATUS_PENDING, SETTLEMENT_STATUS_PROCESSING, 
    SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED,
    TRANSACTION_TYPE_WITHDRAWAL, TRANSACTION_STATUS_SUCCESS
)
from wallet.exceptions import SettlementError, InsufficientFunds
from wallet.services.paystack_service import PaystackService
from wallet.settings import get_wallet_setting


logger = logging.getLogger(__name__)


class SettlementService:
    """
    Service for handling wallet settlements
    """
    def __init__(self):
        self.paystack = PaystackService()
    
    def get_settlement(self, settlement_id):
        """
        Get a settlement by ID
        
        Args:
            settlement_id: Settlement ID
            
        Returns:
            Settlement: Settlement object
        """
        return Settlement.objects.get(id=settlement_id)
    
    def get_settlement_by_reference(self, reference):
        """
        Get a settlement by reference
        
        Args:
            reference (str): Settlement reference
            
        Returns:
            Settlement: Settlement object
        """
        return Settlement.objects.get(reference=reference)
    
    def list_settlements(self, wallet=None, status=None, start_date=None, end_date=None):
        """
        List settlements with optional filtering
        
        Args:
            wallet (Wallet, optional): Filter by wallet
            status (str, optional): Filter by status
            start_date (datetime, optional): Filter by start date
            end_date (datetime, optional): Filter by end date
            
        Returns:
            QuerySet: Filtered settlements
        """
        queryset = Settlement.objects.all()
        
        if wallet:
            queryset = queryset.filter(wallet=wallet)
            
        if status:
            queryset = queryset.filter(status=status)
            
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
            
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        return queryset.order_by('-created_at')
    
    def create_settlement_schedule(self, wallet, bank_account, schedule_type='manual', 
                                  amount_threshold=None, minimum_amount=0, maximum_amount=None, 
                                  day_of_week=None, day_of_month=None, time_of_day=None):
        """
        Create a settlement schedule for a wallet
        
        Args:
            wallet (Wallet): Wallet to create schedule for
            bank_account (BankAccount): Bank account to settle to
            schedule_type (str): Type of schedule (daily, weekly, monthly, threshold, manual)
            amount_threshold (Decimal, optional): Threshold amount for settlement
            minimum_amount (Decimal): Minimum amount to settle
            maximum_amount (Decimal, optional): Maximum amount to settle
            day_of_week (int, optional): Day of week for weekly settlements (0=Monday, 6=Sunday)
            day_of_month (int, optional): Day of month for monthly settlements
            time_of_day (time, optional): Time of day for the settlement
            
        Returns:
            SettlementSchedule: Created schedule
        """
        # Validate schedule parameters
        if schedule_type == 'weekly' and day_of_week is None:
            raise ValueError(_("Day of week is required for weekly schedules"))
            
        if schedule_type == 'monthly' and day_of_month is None:
            raise ValueError(_("Day of month is required for monthly schedules"))
            
        if schedule_type == 'threshold' and amount_threshold is None:
            raise ValueError(_("Amount threshold is required for threshold schedules"))
        
        # Create schedule
        schedule = SettlementSchedule.objects.create(
            wallet=wallet,
            bank_account=bank_account,
            schedule_type=schedule_type,
            amount_threshold=amount_threshold,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            time_of_day=time_of_day
        )
        
        # Calculate next settlement date for scheduled settlements
        if schedule_type in ['daily', 'weekly', 'monthly']:
            schedule.calculate_next_settlement()
        
        return schedule
    
    def update_settlement_schedule(self, schedule, **kwargs):
        """
        Update a settlement schedule
        
        Args:
            schedule (SettlementSchedule): Schedule to update
            **kwargs: Fields to update
            
        Returns:
            SettlementSchedule: Updated schedule
        """
        # Update fields
        for field, value in kwargs.items():
            setattr(schedule, field, value)
            
        schedule.save()
        
        # Recalculate next settlement date if relevant fields changed
        recalculate_fields = [
            'schedule_type', 'is_active', 
            'day_of_week', 'day_of_month', 'time_of_day'
        ]
        
        if any(field in kwargs for field in recalculate_fields):
            if schedule.schedule_type in ['daily', 'weekly', 'monthly'] and schedule.is_active:
                schedule.calculate_next_settlement()
        
        return schedule
    
    def delete_settlement_schedule(self, schedule):
        """
        Delete a settlement schedule
        
        Args:
            schedule (SettlementSchedule): Schedule to delete
            
        Returns:
            bool: True if deleted
        """
        schedule.delete()
        return True
    
    @transaction.atomic
    def create_settlement(self, wallet, bank_account, amount, reason=None, metadata=None):
        """
        Create a new settlement
        
        Args:
            wallet (Wallet): Wallet to settle from
            bank_account (BankAccount): Bank account to settle to
            amount (Decimal): Amount to settle
            reason (str, optional): Reason for settlement
            metadata (dict, optional): Additional metadata
            
        Returns:
            Settlement: Created settlement
            
        Raises:
            SettlementError: If settlement fails
            InsufficientFunds: If wallet has insufficient funds
        """
        # Validate bank account has recipient code
        if not bank_account.paystack_recipient_code:
            raise SettlementError(_("Bank account does not have a recipient code"))
        
        # Validate amount
        if amount <= 0:
            raise SettlementError(_("Settlement amount must be greater than zero"))
        
        # Ensure wallet has sufficient funds
        if wallet.balance.amount < amount:
            raise InsufficientFunds(wallet, amount)
        
        # Generate reference
        from wallet.utils.id_generators import generate_settlement_reference
        reference = generate_settlement_reference()
        
        # Create settlement record
        settlement = Settlement.objects.create(
            wallet=wallet,
            bank_account=bank_account,
            amount=amount,
            status=SETTLEMENT_STATUS_PENDING,
            reference=reference,
            reason=reason,
            metadata=metadata or {}
        )
        
        # Create transaction for the settlement
        transaction = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_SUCCESS,
            description=reason or _("Settlement to bank account"),
            reference=f"STL-{settlement.reference}",
            recipient_bank_account=bank_account
        )
        
        # Link transaction to settlement
        settlement.transaction = transaction
        settlement.save(update_fields=['transaction'])
        
        # Process the settlement
        try:
            self.process_settlement(settlement)
            return settlement
        except Exception as e:
            # Refund wallet if settlement failed
            try:
                wallet.deposit(amount)
            except Exception as refund_error:
                logger.error(f"Error refunding wallet after failed settlement: {str(refund_error)}")
            
            # Mark settlement as failed
            settlement.status = SETTLEMENT_STATUS_FAILED
            settlement.failure_reason = str(e)
            settlement.save(update_fields=['status', 'failure_reason'])
            
            # Raise specific error
            raise SettlementError(str(e), settlement.reference) from e
    
    @transaction.atomic
    def process_settlement(self, settlement):
        """
        Process a pending settlement
        
        Args:
            settlement (Settlement): Settlement to process
            
        Returns:
            Settlement: Updated settlement
            
        Raises:
            SettlementError: If settlement processing fails
        """
        # Verify settlement is in pending status
        if settlement.status != SETTLEMENT_STATUS_PENDING:
            raise SettlementError(_("Only pending settlements can be processed"))
        
        # Mark as processing
        settlement.status = SETTLEMENT_STATUS_PROCESSING
        settlement.save(update_fields=['status'])
        
        try:
            # Convert amount to kobo/cents
            amount_in_minor_unit = int(settlement.amount.amount * 100)
            
            # Create bank transfer using Paystack
            transfer_data = self.paystack.initiate_transfer(
                amount=amount_in_minor_unit,
                recipient_code=settlement.bank_account.paystack_recipient_code,
                reference=settlement.reference,
                reason=settlement.reason or _("Settlement to bank account")
            )
            
            # Update settlement with Paystack data
            settlement.paystack_transfer_code = transfer_data.get('transfer_code')
            settlement.paystack_transfer_data = transfer_data
            
            # Update status based on Paystack response
            if transfer_data.get('status') == 'success':
                settlement.status = SETTLEMENT_STATUS_SUCCESS
                settlement.settled_at = timezone.now()
            else:
                settlement.status = SETTLEMENT_STATUS_PENDING  # Still pending, will be updated by webhook
            
            settlement.save()
            
            return settlement
            
        except Exception as e:
            # Mark settlement as failed
            settlement.status = SETTLEMENT_STATUS_FAILED
            settlement.failure_reason = str(e)
            settlement.save(update_fields=['status', 'failure_reason'])
            
            # Re-raise with more context
            raise SettlementError(str(e), settlement.reference) from e
    
    def verify_settlement(self, settlement):
        """
        Verify a settlement's status with Paystack
        
        Args:
            settlement (Settlement): Settlement to verify
            
        Returns:
            Settlement: Updated settlement
        """
        if not settlement.paystack_transfer_code:
            raise SettlementError(_("Settlement does not have a Paystack transfer code"))
        
        try:
            # Get settlement status from Paystack
            transfer_data = self.paystack.verify_transfer(settlement.reference)
            
            # Update settlement with latest data
            settlement.paystack_transfer_data = transfer_data
            
            # Update status based on Paystack status
            status = transfer_data.get('status')
            
            if status == 'success':
                settlement.status = SETTLEMENT_STATUS_SUCCESS
                settlement.settled_at = timezone.now()
            elif status == 'failed':
                settlement.status = SETTLEMENT_STATUS_FAILED
                settlement.failure_reason = transfer_data.get('reason')
            
            settlement.save()
            
            return settlement
            
        except Exception as e:
            logger.error(f"Error verifying settlement {settlement.reference}: {str(e)}")
            # Don't change settlement status based on verification error
            return settlement
    
    def process_due_settlements(self):
        """
        Process all due scheduled settlements - Money field consistent version
        
        Returns:
            int: Number of settlements processed
        """
        now = timezone.now()
        count = 0
        
        # Get all active schedules with due next_settlement date
        due_schedules = SettlementSchedule.objects.filter(
            is_active=True,
            next_settlement__lte=now
        ).exclude(
            schedule_type='manual'
        ).select_related('wallet', 'bank_account')
        
        for schedule in due_schedules:
            try:
                # Determine settlement amount - should return Money object
                amount = self._calculate_settlement_amount(schedule)
                
                # Check if amount is positive (handle Money object properly)
                if amount.amount > 0:  # Compare the decimal part
                    # Create settlement
                    self.create_settlement(
                        wallet=schedule.wallet,
                        bank_account=schedule.bank_account,
                        amount=amount,  # Pass Money object
                        reason=f"Scheduled {schedule.get_schedule_type_display()} settlement",
                        metadata={
                            'schedule_id': str(schedule.id),
                            'schedule_type': schedule.schedule_type
                        }
                    )
                    count += 1
                
                # Update schedule
                schedule.last_settlement = now
                schedule.calculate_next_settlement()
                schedule.save(update_fields=['last_settlement', 'next_settlement'])
                
            except Exception as e:
                logger.error(f"Error processing scheduled settlement for {schedule.id}: {str(e)}")
        
        # Handle threshold-based schedules
        threshold_schedules = SettlementSchedule.objects.filter(
            is_active=True,
            schedule_type='threshold'
        ).exclude(
            amount_threshold=None
        ).select_related('wallet', 'bank_account')
        
        for schedule in threshold_schedules:
            try:
                # Check if balance exceeds threshold (compare Money objects)
                if schedule.wallet.balance >= schedule.amount_threshold:
                    # Determine settlement amount
                    amount = self._calculate_settlement_amount(schedule)
                    
                    # Check if amount is positive
                    if amount.amount > 0:
                        # Create settlement
                        self.create_settlement(
                            wallet=schedule.wallet,
                            bank_account=schedule.bank_account,
                            amount=amount,  # Pass Money object
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
            except Exception as e:
                logger.error(f"Error processing threshold settlement for {schedule.id}: {str(e)}")
        
        return count

    
    def _calculate_settlement_amount(self, schedule):
        """
        Calculate the settlement amount for a given schedule.

        Args:
            schedule (SettlementSchedule): The settlement schedule.

        Returns:
            Money: The amount to settle.
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

        # Apply minimum settlement amount
        if available_balance < schedule.minimum_amount:
            return Money(0, wallet_balance.currency)

        # Apply maximum settlement amount if configured
        if schedule.maximum_amount is not None and available_balance > schedule.maximum_amount:
            return schedule.maximum_amount

        return available_balance
    
    def process_paystack_webhook(self, event_type, data):
        """
        Process a Paystack webhook event related to settlements
        
        Args:
            event_type (str): Webhook event type
            data (dict): Webhook event data
            
        Returns:
            bool: True if processed successfully
        """
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
        return False
    
    def _process_transfer_success(self, data):
        """Process transfer.success webhook event for settlements"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        
        # Find settlement by reference or transfer code
        settlement = Settlement.objects.filter(
            reference=reference
        ).first()
        
        if not settlement and transfer_code:
            settlement = Settlement.objects.filter(
                paystack_transfer_code=transfer_code
            ).first()
        
        if settlement:
            # Update settlement status
            settlement.status = SETTLEMENT_STATUS_SUCCESS
            settlement.settled_at = timezone.now()
            settlement.paystack_transfer_data = data
            settlement.save()
            
            return True
        
        return False
    
    def _process_transfer_failed(self, data):
        """Process transfer.failed webhook event for settlements"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason', _("Transfer failed"))
        
        # Find settlement by reference or transfer code
        settlement = Settlement.objects.filter(
            reference=reference
        ).first()
        
        if not settlement and transfer_code:
            settlement = Settlement.objects.filter(
                paystack_transfer_code=transfer_code
            ).first()
        
        if settlement:
            # Update settlement status
            settlement.status = SETTLEMENT_STATUS_FAILED
            settlement.failure_reason = reason
            settlement.paystack_transfer_data = data
            settlement.save()
            
            # Refund the wallet
            try:
                settlement.wallet.deposit(settlement.amount.amount)
                
                # Update transaction status
                if settlement.transaction:
                    settlement.transaction.status = 'failed'
                    settlement.transaction.failed_reason = reason
                    settlement.transaction.save(update_fields=['status', 'failed_reason'])
            except Exception as e:
                logger.error(f"Error refunding wallet after failed settlement {settlement.reference}: {str(e)}")
            
            return True
        
        return False
    
    def _process_transfer_reversed(self, data):
        """Process transfer.reversed webhook event for settlements"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason', _("Transfer reversed"))
        
        # Find settlement by reference or transfer code
        settlement = Settlement.objects.filter(
            reference=reference
        ).first()
        
        if not settlement and transfer_code:
            settlement = Settlement.objects.filter(
                paystack_transfer_code=transfer_code
            ).first()
        
        if settlement:
            # Update settlement status
            settlement.status = SETTLEMENT_STATUS_FAILED
            settlement.failure_reason = reason
            settlement.paystack_transfer_data = data
            settlement.save()
            
            # Refund the wallet
            try:
                settlement.wallet.deposit(settlement.amount.amount)
                
                # Update transaction status
                if settlement.transaction:
                    settlement.transaction.status = 'reversed'
                    settlement.transaction.failed_reason = reason
                    settlement.transaction.save(update_fields=['status', 'failed_reason'])
            except Exception as e:
                logger.error(f"Error refunding wallet after reversed settlement {settlement.reference}: {str(e)}")
            
            return True
        
        return False