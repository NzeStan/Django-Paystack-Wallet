"""
Django Paystack Wallet - Settlement Service (COMPLETE VERSION)
Comprehensive business logic with OTP support, statistics, and all features

INCLUDES:
- OTP flow and finalization
- Settlement statistics
- All CRUD operations
- Webhook processing
- Schedule management
- Analytics methods
"""
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, List
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ObjectDoesNotExist
from djmoney.money import Money
from datetime import timedelta

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
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED
)
from wallet.exceptions import (
    SettlementError,
    InsufficientFunds,
    InvalidAmount,
    WalletLocked,
    PaystackAPIError
)
from wallet.services.paystack_service import PaystackService
from wallet.settings import get_wallet_setting


logger = logging.getLogger(__name__)


class SettlementService:
    """
    Service for handling wallet settlements with OTP support
    
    This service provides comprehensive settlement management including:
    - Settlement creation with proper transaction ordering
    - OTP-based settlement finalization
    - Paystack integration
    - Webhook processing
    - Settlement schedules
    - Settlement verification
    - Statistics and analytics
    
    CRITICAL: Settlements follow the same pattern as withdrawals:
    1. Create Transaction record BEFORE Paystack call
    2. Call Paystack API
    3. If OTP required → keep PENDING, don't touch wallet
    4. User provides OTP → finalize_settlement() → withdraw from wallet
    5. Webhooks find existing transaction immediately
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
            # Use custom QuerySet method for optimized retrieval
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
            settlement = Settlement.objects.with_full_details().get(reference=reference)
            logger.debug(f"Retrieved settlement by reference {reference}")
            return settlement
        except ObjectDoesNotExist:
            logger.error(f"Settlement with reference {reference} not found")
            raise
    
    def get_settlements_for_wallet(
        self,
        wallet: Wallet,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Settlement]:
        """
        Get settlements for a wallet
        
        Args:
            wallet: Wallet instance
            status: Filter by status (optional)
            limit: Maximum number of results
            
        Returns:
            List[Settlement]: List of settlements
        """
        queryset = Settlement.objects.by_wallet(wallet).with_full_details()
        
        if status:
            queryset = queryset.filter(status=status)
        
        settlements = list(queryset[:limit])
        
        logger.debug(
            f"Retrieved {len(settlements)} settlements for wallet {wallet.id}"
        )
        
        return settlements
    
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
        
        CRITICAL: This method now follows the withdrawal pattern:
        1. Create Settlement record FIRST
        2. Create Transaction record (PENDING status)
        3. Process settlement (calls Paystack)
        4. If OTP required → return with PENDING status (wallet NOT touched)
        5. If success → withdraw from wallet
        
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
            # ✅ STEP 1: Create settlement record FIRST
            settlement = Settlement.objects.create(
                wallet=wallet,
                bank_account=bank_account,
                amount=amount,
                status=SETTLEMENT_STATUS_PENDING,
                reference=reference,
                reason=reason or _("Settlement to bank account"),
                metadata=metadata or {}
            )
            
            logger.info(
                f"Created settlement {settlement.id} with reference {reference} "
                f"(PENDING status, wallet NOT yet deducted)"
            )
            
            # ✅ STEP 2: Create transaction record (BEFORE Paystack call)
            transaction_obj = Transaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
                status=TRANSACTION_STATUS_PENDING,
                description=reason or _("Settlement to bank account"),
                reference=f"STL-{settlement.reference}",
                recipient_bank_account=bank_account,
                metadata={
                    'settlement_id': str(settlement.id),
                    'settlement_reference': settlement.reference
                }
            )
            
            logger.info(
                f"Created transaction {transaction_obj.id} for settlement {settlement.id} "
                f"(PENDING status - awaiting confirmation)"
            )
            
            # Link transaction to settlement
            settlement.transaction = transaction_obj
            settlement.save(update_fields=['transaction'])
            
            # ✅ STEP 3: Process the settlement if auto_process is True
            if auto_process:
                logger.debug(f"Auto-processing settlement {settlement.id}")
                return self.process_settlement(settlement)
            
            return settlement
            
        except Exception as e:
            logger.error(
                f"Error creating settlement: {str(e)}",
                exc_info=True
            )
            raise SettlementError(
                _("Failed to create settlement: %(error)s") % {'error': str(e)}
            ) from e
    
    # ==========================================
    # SETTLEMENT PROCESSING
    # ==========================================
    
    @db_transaction.atomic
    def process_settlement(self, settlement: Settlement) -> Settlement:
        """
        Process a pending settlement
        
        This method calls Paystack and handles the OTP flow:
        - If Paystack returns OTP required → keep PENDING, don't touch wallet
        - If Paystack returns success → withdraw from wallet immediately
        - If Paystack returns error → mark failed, no wallet action needed
        
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
            # Convert amount to kobo/cents
            amount_in_minor_unit = int(settlement.amount.amount * 100)
            
            logger.debug(
                f"Initiating Paystack transfer: amount={amount_in_minor_unit}, "
                f"recipient={settlement.bank_account.paystack_recipient_code}"
            )
            
            # ✅ STEP 4: Call Paystack API to initiate transfer
            transfer_data = self.paystack.initiate_transfer(
                amount=amount_in_minor_unit,
                recipient_code=settlement.bank_account.paystack_recipient_code,
                reference=settlement.reference,
                reason=settlement.reason or _("Settlement to bank account")
            )
            
            logger.info(
                f"Paystack transfer initiated for settlement {settlement.id}: "
                f"transfer_code={transfer_data.get('transfer_code')}, "
                f"status={transfer_data.get('status')}"
            )
            
            # ✅ Store the transfer code for OTP finalization
            transfer_code = transfer_data.get('transfer_code')
            if not transfer_code:
                raise PaystackAPIError("Paystack did not return a transfer code")
            
            settlement.paystack_transfer_code = transfer_code
            settlement.paystack_transfer_data = transfer_data
            
            # ✅ STEP 5: Check if OTP is required
            requires_otp = transfer_data.get('requires_otp', False)
            transfer_status = transfer_data.get('status', 'pending')
            
            if requires_otp or transfer_status == 'otp':
                # ✅ OTP REQUIRED - Keep settlement PENDING
                settlement.status = SETTLEMENT_STATUS_PENDING
                settlement.save(update_fields=[
                    'paystack_transfer_code',
                    'paystack_transfer_data',
                    'status'
                ])
                
                logger.info(
                    f"Settlement {settlement.id} requires OTP verification. "
                    f"Wallet balance NOT yet withdrawn."
                )
                
                return settlement
            
            # ✅ STEP 6: No OTP needed - check if immediately successful
            if transfer_status == 'success':
                # ✅ Withdraw from wallet NOW
                with db_transaction.atomic():
                    locked_wallet = Wallet.objects.select_for_update().get(
                        id=settlement.wallet.id
                    )
                    locked_wallet.withdraw(settlement.amount.amount)
                
                logger.info(
                    f"Withdrew {settlement.amount} from wallet {settlement.wallet.id} "
                    f"after immediate Paystack success"
                )
                
                # Mark settlement as successful
                settlement.mark_as_success(transfer_data)
                
                # Update transaction status
                if settlement.transaction:
                    settlement.transaction.status = TRANSACTION_STATUS_SUCCESS
                    settlement.transaction.paystack_reference = transfer_code
                    settlement.transaction.paystack_response = transfer_data
                    settlement.transaction.completed_at = timezone.now()
                    settlement.transaction.save(update_fields=[
                        'status',
                        'paystack_reference',
                        'paystack_response',
                        'completed_at'
                    ])
            else:
                # Still pending Paystack confirmation
                settlement.status = SETTLEMENT_STATUS_PENDING
                settlement.save(update_fields=[
                    'paystack_transfer_code',
                    'paystack_transfer_data',
                    'status'
                ])
            
            return settlement
            
        except PaystackAPIError as e:
            logger.error(
                f"Paystack API error processing settlement {settlement.id}: {str(e)}",
                exc_info=True
            )
            
            settlement.mark_as_failed(str(e))
            
            if settlement.transaction:
                settlement.transaction.status = TRANSACTION_STATUS_FAILED
                settlement.transaction.failed_reason = str(e)
                settlement.transaction.save(update_fields=['status', 'failed_reason'])
            
            raise SettlementError(
                f"Settlement processing failed: {str(e)}",
                settlement.reference
            ) from e
        
        except Exception as e:
            logger.error(
                f"Error processing settlement {settlement.id}: {str(e)}",
                exc_info=True
            )
            
            settlement.mark_as_failed(str(e))
            
            if settlement.transaction:
                settlement.transaction.status = TRANSACTION_STATUS_FAILED
                settlement.transaction.failed_reason = str(e)
                settlement.transaction.save(update_fields=['status', 'failed_reason'])
            
            raise SettlementError(
                f"Settlement processing failed: {str(e)}",
                settlement.reference
            ) from e
    
    # ==========================================
    # SETTLEMENT FINALIZATION (OTP)
    # ==========================================
    
    @db_transaction.atomic
    def finalize_settlement(
        self,
        settlement: Settlement,
        otp: str
    ) -> Dict[str, Any]:
        """
        Finalize a pending settlement with OTP
        
        Args:
            settlement: Pending settlement awaiting OTP
            otp: One-Time Password received by user
            
        Returns:
            dict: Finalization response from Paystack
            
        Raises:
            SettlementError: If settlement invalid or finalization fails
        """
        logger.info(f"Finalizing settlement {settlement.id} with OTP")
        
        if settlement.status != SETTLEMENT_STATUS_PENDING:
            raise SettlementError(
                _("Settlement is not pending. Current status: %(status)s") % {
                    'status': settlement.get_status_display()
                }
            )
        
        if not settlement.paystack_transfer_code:
            raise SettlementError(_("Settlement does not have a transfer code"))
        
        try:
            # Call Paystack to finalize with OTP
            finalize_data = self.paystack.finalize_transfer(
                transfer_code=settlement.paystack_transfer_code,
                otp=otp
            )
            
            settlement.paystack_transfer_data = finalize_data
            final_status = finalize_data.get('status')
            
            if final_status == 'success':
                # ✅ Withdraw from wallet NOW
                with db_transaction.atomic():
                    locked_wallet = Wallet.objects.select_for_update().get(
                        id=settlement.wallet.id
                    )
                    locked_wallet.withdraw(settlement.amount.amount)
                
                settlement.mark_as_success(finalize_data)
                
                if settlement.transaction:
                    settlement.transaction.status = TRANSACTION_STATUS_SUCCESS
                    settlement.transaction.paystack_reference = settlement.paystack_transfer_code
                    settlement.transaction.paystack_response = finalize_data
                    settlement.transaction.completed_at = timezone.now()
                    settlement.transaction.save()
                
                return finalize_data
                
            elif final_status == 'failed':
                failure_reason = finalize_data.get('message', 'Transfer failed')
                settlement.mark_as_failed(failure_reason, finalize_data)
                
                if settlement.transaction:
                    settlement.transaction.status = TRANSACTION_STATUS_FAILED
                    settlement.transaction.failed_reason = failure_reason
                    settlement.transaction.save()
                
                raise SettlementError(
                    _("Settlement failed: %(reason)s") % {'reason': failure_reason}
                )
            else:
                settlement.save(update_fields=['paystack_transfer_data'])
                return finalize_data
                
        except PaystackAPIError as e:
            settlement.mark_as_failed(str(e))
            if settlement.transaction:
                settlement.transaction.status = TRANSACTION_STATUS_FAILED
                settlement.transaction.failed_reason = str(e)
                settlement.transaction.save()
            raise
        except Exception as e:
            raise SettlementError(
                _("Failed to finalize settlement: %(error)s") % {'error': str(e)}
            ) from e
    
    # ==========================================
    # SETTLEMENT VERIFICATION
    # ==========================================
    
    def verify_settlement(self, settlement: Settlement) -> Settlement:
        """Verify a settlement's status with Paystack"""
        logger.info(f"Verifying settlement {settlement.id}")
        
        if not settlement.paystack_transfer_code:
            raise SettlementError(
                _("Settlement does not have a Paystack transfer code")
            )
        
        try:
            transfer_data = self.paystack.verify_transfer(settlement.reference)
            settlement.paystack_transfer_data = transfer_data
            paystack_status = transfer_data.get('status')
            
            if paystack_status == 'success':
                settlement.mark_as_success(transfer_data)
            elif paystack_status == 'failed':
                settlement.mark_as_failed(transfer_data.get('reason'), transfer_data)
            else:
                settlement.save(update_fields=['paystack_transfer_data'])
            
            return settlement
        except Exception as e:
            logger.error(f"Error verifying settlement: {str(e)}", exc_info=True)
            return settlement
    
    # ==========================================
    # SETTLEMENT STATISTICS AND ANALYTICS
    # ==========================================
    
    def get_settlement_stats(
        self,
        wallet: Optional[Wallet] = None,
        start_date: Optional[timezone.datetime] = None,
        end_date: Optional[timezone.datetime] = None
    ) -> Dict[str, Any]:
        """
        Get settlement statistics
        
        Args:
            wallet: Filter by wallet (optional)
            start_date: Start date for filtering (optional)
            end_date: End date for filtering (optional)
            
        Returns:
            dict: Settlement statistics
        """
        logger.info("Calculating settlement statistics")
        
        # Start with base queryset
        queryset = Settlement.objects.all()
        
        # Apply wallet filter
        if wallet:
            queryset = queryset.by_wallet(wallet)
        
        # Apply date range
        if start_date or end_date:
            queryset = queryset.in_date_range(start_date, end_date)
        
        # Calculate statistics
        stats = queryset.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            average_amount=Avg('amount'),
            successful_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_SUCCESS)),
            failed_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_FAILED)),
            pending_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_PENDING)),
        )
        
        # Get successful settlements only
        successful_settlements = queryset.successful()
        
        # Calculate success metrics
        stats['success_rate'] = 0
        if stats['total_count'] > 0:
            stats['success_rate'] = (
                stats['successful_count'] / stats['total_count']
            ) * 100
        
        # Get recent settlements
        stats['recent_settlements'] = list(
            queryset.order_by('-created_at')[:10].values(
                'id',
                'reference',
                'amount',
                'status',
                'created_at',
                'settled_at'
            )
        )
        
        logger.info(
            f"Settlement stats: {stats['total_count']} total, "
            f"{stats['successful_count']} successful, "
            f"{stats['success_rate']:.2f}% success rate"
        )
        
        return stats
    
    def get_settlement_summary(
        self,
        wallet: Wallet,
        period_days: int = 30
    ) -> Dict[str, Any]:
        """
        Get settlement summary for a wallet
        
        Args:
            wallet: Wallet instance
            period_days: Number of days to include in summary
            
        Returns:
            dict: Settlement summary
        """
        logger.info(f"Getting settlement summary for wallet {wallet.id}")
        
        start_date = timezone.now() - timedelta(days=period_days)
        
        # Get settlements in period
        settlements = Settlement.objects.by_wallet(wallet).in_date_range(
            start_date=start_date
        )
        
        # Calculate summary
        summary = settlements.aggregate(
            total_settled=Sum('amount', filter=Q(status=SETTLEMENT_STATUS_SUCCESS)),
            settlement_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_SUCCESS)),
            pending_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_PENDING)),
            failed_count=Count('id', filter=Q(status=SETTLEMENT_STATUS_FAILED)),
        )
        
        # Add period info
        summary['period_days'] = period_days
        summary['period_start'] = start_date
        summary['period_end'] = timezone.now()
        
        logger.debug(f"Settlement summary: {summary}")
        
        return summary
    
    def get_top_settlement_destinations(
        self,
        wallet: Wallet,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get top settlement destinations (bank accounts) for a wallet
        
        Args:
            wallet: Wallet instance
            limit: Number of results to return
            
        Returns:
            List[dict]: Top destinations with settlement counts and amounts
        """
        logger.info(f"Getting top settlement destinations for wallet {wallet.id}")
        
        # Get successful settlements grouped by bank account
        destinations = Settlement.objects.by_wallet(wallet).successful().values(
            'bank_account__id',
            'bank_account__account_name',
            'bank_account__account_number',
            'bank_account__bank__name'
        ).annotate(
            settlement_count=Count('id'),
            total_amount=Sum('amount')
        ).order_by('-total_amount')[:limit]
        
        return list(destinations)
    
    # ==========================================
    # SETTLEMENT RETRY
    # ==========================================
    
    @db_transaction.atomic
    def retry_settlement(self, settlement: Settlement) -> Settlement:
        """Retry a failed settlement"""
        logger.info(f"Retrying settlement {settlement.id}")
        
        if settlement.status != SETTLEMENT_STATUS_FAILED:
            raise SettlementError(_("Only failed settlements can be retried"))
        
        if settlement.wallet.balance.amount < settlement.amount.amount:
            raise InsufficientFunds(settlement.wallet, settlement.amount.amount)
        
        settlement.status = SETTLEMENT_STATUS_PENDING
        settlement.failure_reason = None
        settlement.save(update_fields=['status', 'failure_reason'])
        
        return self.process_settlement(settlement)
    
    # ==========================================
    # WEBHOOK PROCESSING
    # ==========================================
    
    def process_paystack_webhook(self, event_type: str, data: Dict) -> bool:
        """Process a Paystack webhook event related to settlements"""
        logger.info(f"Processing webhook event: {event_type}")
        
        if event_type == 'transfer.success':
            return self._process_transfer_success(data)
        elif event_type == 'transfer.failed':
            return self._process_transfer_failed(data)
        elif event_type == 'transfer.reversed':
            return self._process_transfer_reversed(data)
        
        return False
    
    @db_transaction.atomic
    def _process_transfer_success(self, data: Dict) -> bool:
        """Process transfer.success webhook"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        
        settlement = self._find_settlement(reference, transfer_code)
        
        if settlement:
            was_pending_otp = (
                settlement.status == SETTLEMENT_STATUS_PENDING and
                settlement.paystack_transfer_code is not None
            )
            
            if was_pending_otp:
                try:
                    with db_transaction.atomic():
                        locked_wallet = Wallet.objects.select_for_update().get(
                            id=settlement.wallet.id
                        )
                        locked_wallet.withdraw(settlement.amount.amount)
                except Exception as e:
                    logger.error(f"Error withdrawing in webhook: {str(e)}")
                    return False
            
            settlement.mark_as_success(data)
            
            if settlement.transaction:
                settlement.transaction.status = TRANSACTION_STATUS_SUCCESS
                settlement.transaction.paystack_reference = transfer_code
                settlement.transaction.paystack_response = data
                settlement.transaction.completed_at = timezone.now()
                settlement.transaction.save()
            
            return True
        
        return False
    
    @db_transaction.atomic
    def _process_transfer_failed(self, data: Dict) -> bool:
        """Process transfer.failed webhook"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason', _("Transfer failed"))
        
        settlement = self._find_settlement(reference, transfer_code)
        
        if settlement:
            settlement.mark_as_failed(reason, data)
            
            if settlement.transaction:
                settlement.transaction.status = TRANSACTION_STATUS_FAILED
                settlement.transaction.failed_reason = reason
                settlement.transaction.save()
            
            return True
        
        return False
    
    @db_transaction.atomic
    def _process_transfer_reversed(self, data: Dict) -> bool:
        """Process transfer.reversed webhook"""
        reference = data.get('reference')
        transfer_code = data.get('transfer_code')
        reason = data.get('reason', _("Transfer reversed"))
        
        settlement = self._find_settlement(reference, transfer_code)
        
        if settlement:
            settlement.status = SETTLEMENT_STATUS_FAILED
            settlement.failure_reason = reason
            settlement.paystack_transfer_data = data
            settlement.save()
            
            if settlement.is_completed:
                try:
                    settlement.wallet.deposit(settlement.amount.amount)
                    
                    if settlement.transaction:
                        settlement.transaction.status = 'reversed'
                        settlement.transaction.failed_reason = reason
                        settlement.transaction.save()
                except Exception as e:
                    logger.error(f"Error refunding after reversal: {str(e)}")
            
            return True
        
        return False
    
    def _find_settlement(
        self,
        reference: Optional[str],
        transfer_code: Optional[str]
    ) -> Optional[Settlement]:
        """Helper to find settlement by reference or transfer code"""
        try:
            if reference:
                return Settlement.objects.filter(reference=reference).first()
            if transfer_code:
                return Settlement.objects.filter(
                    paystack_transfer_code=transfer_code
                ).first()
        except Exception as e:
            logger.error(f"Error finding settlement: {str(e)}")
        
        return None
    
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
        """Create a new settlement schedule"""
        logger.info(
            f"Creating settlement schedule: wallet={wallet.id}, type={schedule_type}"
        )
        
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
        """Process all due scheduled settlements"""
        logger.info("Processing due settlement schedules")
        
        now = timezone.now()
        count = 0
        
        # Use custom QuerySet methods
        due_schedules = SettlementSchedule.objects.due_now().with_full_details()
        
        logger.info(f"Found {due_schedules.count()} due schedules")
        
        for schedule in due_schedules:
            try:
                amount = self._calculate_settlement_amount(schedule)
                
                if amount.amount > 0:
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
                
                schedule.last_settlement = now
                schedule.calculate_next_settlement()
                schedule.save(update_fields=['last_settlement', 'next_settlement'])
                
            except Exception as e:
                logger.error(f"Error processing schedule {schedule.id}: {str(e)}")
                continue
        
        logger.info(f"Processed {count} scheduled settlements")
        return count
    
    def _calculate_settlement_amount(self, schedule: SettlementSchedule) -> Money:
        """Calculate settlement amount based on schedule rules"""
        wallet = schedule.wallet
        balance = wallet.balance
        amount = balance.amount
        
        if amount < schedule.minimum_amount.amount:
            return Money(0, balance.currency)
        
        if schedule.maximum_amount and amount > schedule.maximum_amount.amount:
            amount = schedule.maximum_amount.amount
        
        if schedule.is_threshold_based and schedule.amount_threshold:
            if balance.amount >= schedule.amount_threshold.amount:
                amount = balance.amount - schedule.amount_threshold.amount
            else:
                amount = 0
        
        return Money(amount, balance.currency)