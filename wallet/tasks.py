import logging
from decimal import Decimal
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from wallet.settings import get_wallet_setting
from wallet.services.wallet_service import WalletService
from wallet.services.settlement_service import SettlementService
from wallet.services.webhook_service import WebhookService


logger = logging.getLogger(__name__)


@shared_task
def create_wallet_for_user_task(user_id):
    """
    Create a wallet for a user (async task)
    
    Args:
        user_id: User ID
    """
    # Get user model
    User = apps.get_model(get_wallet_setting('USER_MODEL'))
    
    try:
        # Get user instance
        user = User.objects.get(pk=user_id)
        
        # Create wallet
        wallet_service = WalletService()
        wallet = wallet_service.get_wallet(user)
        
        logger.info(f"Created wallet {wallet.id} for user {user_id}")
        return str(wallet.id)
    except Exception as e:
        logger.error(f"Error creating wallet for user {user_id}: {str(e)}")
        raise


@shared_task
def create_dedicated_account_task(wallet_id):
    """
    Create a dedicated virtual account for a wallet (async task)
    
    Args:
        wallet_id: Wallet ID
    """
    # Get wallet model
    Wallet = apps.get_model('wallet', 'Wallet')
    
    try:
        # Get wallet instance
        wallet = Wallet.objects.get(pk=wallet_id)
        
        # Create dedicated account
        wallet_service = WalletService()
        result = wallet_service.create_dedicated_account(wallet)
        
        logger.info(f"Created dedicated account for wallet {wallet_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Error creating dedicated account for wallet {wallet_id}: {str(e)}")
        raise


@shared_task(bind=True, max_retries=3)
def process_wallet_settlement_schedules_task(self, wallet_id):
    """
    Process settlement schedules for a wallet (async task)
    
    OPTIMIZED:
    - Proper error handling with retries
    - select_for_update to prevent race conditions
    - select_related for QuerySet optimization
    - Atomic transactions per settlement
    - Comprehensive logging
    
    Args:
        wallet_id: Wallet ID
        
    Returns:
        int: Number of settlements processed
        
    Raises:
        Exception: On critical errors (will trigger retry)
    """
    from wallet.services.settlement_service import SettlementService
    
    # Get models
    Wallet = apps.get_model('wallet', 'Wallet')
    SettlementSchedule = apps.get_model('wallet', 'SettlementSchedule')
    
    try:
        logger.info(
            f"[Task] Processing settlement schedules for wallet {wallet_id}"
        )
        
        # ✅ Get wallet with lock to prevent race conditions
        # This ensures only one task processes this wallet at a time
        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
        
        # Get settlement service
        settlement_service = SettlementService()
        
        # ✅ OPTIMIZED: Get schedules with select_related
        # This loads wallet, user, bank_account, and bank in ONE query
        schedules = SettlementSchedule.objects.filter(
            wallet=wallet,
            is_active=True,
            schedule_type='threshold'
        ).exclude(
            amount_threshold=None
        ).select_related(
            'wallet',
            'wallet__user',
            'bank_account',
            'bank_account__bank'
        )
        
        schedule_count = schedules.count()
        logger.info(
            f"[Task] Found {schedule_count} active threshold schedules "
            f"for wallet {wallet_id}"
        )
        
        if schedule_count == 0:
            logger.debug(
                f"[Task] No active threshold schedules for wallet {wallet_id}, skipping"
            )
            return 0
        
        settlements_created = 0
        
        # Process each schedule
        for schedule in schedules:
            try:
                # Check if balance exceeds threshold
                if wallet.balance.amount >= schedule.amount_threshold.amount:
                    # Calculate settlement amount
                    amount = settlement_service._calculate_settlement_amount(schedule)
                    
                    if amount.amount > 0:
                        logger.info(
                            f"[Task] Creating settlement for schedule {schedule.id}: "
                            f"amount={amount}, threshold={schedule.amount_threshold}"
                        )
                        
                        # ✅ Create settlement with atomic transaction
                        # This ensures either ALL changes succeed or NONE do
                        with transaction.atomic():
                            settlement = settlement_service.create_settlement(
                                wallet=wallet,
                                bank_account=schedule.bank_account,
                                amount=amount,
                                reason="Automatic threshold-based settlement",
                                metadata={
                                    'schedule_id': str(schedule.id),
                                    'schedule_type': 'threshold',
                                    'threshold': str(schedule.amount_threshold.amount),
                                    'processed_by': 'celery_task'
                                }
                            )
                            
                            # Update schedule last settlement time
                            schedule.last_settlement = timezone.now()
                            schedule.save(update_fields=['last_settlement'])
                        
                        settlements_created += 1
                        
                        logger.info(
                            f"[Task] Successfully created settlement {settlement.id} "
                            f"for schedule {schedule.id}"
                        )
                    else:
                        logger.debug(
                            f"[Task] Schedule {schedule.id} calculated amount is {amount}, "
                            f"skipping (not positive)"
                        )
                else:
                    logger.debug(
                        f"[Task] Schedule {schedule.id} threshold not met: "
                        f"balance={wallet.balance.amount}, "
                        f"threshold={schedule.amount_threshold.amount}"
                    )
                    
            except Exception as e:
                # Log error but continue with other schedules
                logger.error(
                    f"[Task] Error processing schedule {schedule.id} "
                    f"for wallet {wallet_id}: {str(e)}",
                    exc_info=True
                )
                # Continue with next schedule instead of failing entire task
                continue
        
        logger.info(
            f"[Task] Processed {settlements_created} settlements "
            f"for wallet {wallet_id}"
        )
        
        return settlements_created
        
    except Wallet.DoesNotExist:
        logger.error(f"[Task] Wallet {wallet_id} not found")
        raise  # Don't retry for non-existent wallet
        
    except Exception as e:
        logger.error(
            f"[Task] Critical error in settlement schedule task "
            f"for wallet {wallet_id}: {str(e)}",
            exc_info=True
        )
        
        # ✅ Retry with exponential backoff
        # First retry: 60 seconds
        # Second retry: 120 seconds
        # Third retry: 240 seconds
        countdown = 60 * (2 ** self.request.retries)
        
        logger.warning(
            f"[Task] Retrying settlement schedule task for wallet {wallet_id} "
            f"in {countdown} seconds (attempt {self.request.retries + 1}/3)"
        )
        
        raise self.retry(exc=e, countdown=countdown)


@shared_task(bind=True, max_retries=2)
def process_due_settlements_task(self):
    """
    Process all due time-based settlement schedules
    
    This task should be run periodically (e.g., every hour) to process
    daily, weekly, and monthly settlement schedules.
    
    Returns:
        dict: Processing statistics
    """
    from wallet.services.settlement_service import SettlementService
    
    try:
        logger.info("[Task] Processing due settlement schedules")
        
        settlement_service = SettlementService()
        
        # Process all due settlements
        count = settlement_service.process_due_settlements()
        
        logger.info(f"[Task] Processed {count} due settlements")
        
        return {
            'status': 'success',
            'settlements_processed': count
        }
        
    except Exception as e:
        logger.error(
            f"[Task] Error processing due settlements: {str(e)}",
            exc_info=True
        )
        
        # Retry with shorter backoff for scheduled tasks
        countdown = 300 * (2 ** self.request.retries)  # 5, 10 minutes
        
        logger.warning(
            f"[Task] Retrying due settlements task in {countdown} seconds "
            f"(attempt {self.request.retries + 1}/2)"
        )
        
        raise self.retry(exc=e, countdown=countdown)


@shared_task
def retry_failed_webhook_deliveries_task():
    """
    Retry all failed webhook deliveries (scheduled task)
    """
    try:
        # Get webhook service
        webhook_service = WebhookService()
        
        # Retry failed deliveries
        count = webhook_service.retry_all_failed_deliveries()
        
        logger.info(f"Retried {count} failed webhook deliveries successfully")
        return count
    except Exception as e:
        logger.error(f"Error retrying failed webhook deliveries: {str(e)}")
        raise


@shared_task
def sync_banks_from_paystack_task(force_update: bool = False):
    """
    Sync banks from Paystack (Celery task wrapper)
    
    This is just a Celery wrapper around the utility function.
    Users without Celery can call the utility directly.
    
    Args:
        force_update (bool): If True, updates existing banks
        
    Returns:
        dict: Statistics about the sync operation
    """
    from wallet.utils.bank_sync import sync_banks_from_paystack
    
    try:
        created, updated, errors = sync_banks_from_paystack(force_update=force_update)
        
        result = {
            'created': created,
            'updated': updated,
            'errors': errors,
            'total': created + updated
        }
        
        logger.info(f"Bank sync task completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error in bank sync task: {str(e)}")
        raise

@shared_task(bind=True, max_retries=2)
def verify_pending_settlements_task(self):
    """
    Verify status of pending settlements with Paystack
    
    This is a safety net for when webhooks don't arrive.
    Run this periodically (e.g., every 30 minutes).
    
    Returns:
        dict: Verification statistics
    """
    from wallet.services.settlement_service import SettlementService
    from wallet.models import Settlement
    from django.utils import timezone
    from datetime import timedelta
    
    try:
        logger.info("[Task] Verifying pending settlements")
        
        settlement_service = SettlementService()
        
        # Get settlements that have been pending for more than 5 minutes
        # and have a Paystack transfer code
        five_minutes_ago = timezone.now() - timedelta(minutes=5)
        
        pending_settlements = Settlement.objects.filter(
            status='pending',
            paystack_transfer_code__isnull=False,
            created_at__lte=five_minutes_ago
        ).select_related(
            'wallet',
            'bank_account',
            'transaction'
        )[:50]  # Limit to 50 per run
        
        verified_count = 0
        updated_count = 0
        
        for settlement in pending_settlements:
            try:
                logger.debug(f"[Task] Verifying settlement {settlement.id}")
                
                # Verify with Paystack
                updated_settlement = settlement_service.verify_settlement(settlement)
                
                verified_count += 1
                
                # Check if status changed
                if updated_settlement.status != 'pending':
                    updated_count += 1
                    logger.info(
                        f"[Task] Settlement {settlement.id} status updated: "
                        f"{updated_settlement.status}"
                    )
                    
            except Exception as e:
                logger.error(
                    f"[Task] Error verifying settlement {settlement.id}: {str(e)}",
                    exc_info=True
                )
                continue
        
        logger.info(
            f"[Task] Verified {verified_count} settlements, "
            f"{updated_count} status updates"
        )
        
        return {
            'status': 'success',
            'verified': verified_count,
            'updated': updated_count
        }
        
    except Exception as e:
        logger.error(
            f"[Task] Error in verify pending settlements: {str(e)}",
            exc_info=True
        )
        
        countdown = 300 * (2 ** self.request.retries)
        raise self.retry(exc=e, countdown=countdown)


@shared_task
def reset_daily_transaction_limits_task():
    """
    Reset daily transaction limits for all wallets (scheduled task)
    """
    # Get models
    Wallet = apps.get_model('wallet', 'Wallet')
    
    try:
        # Get today's date
        today = timezone.now().date()
        
        # Find wallets with outdated daily limits
        wallets = Wallet.objects.exclude(daily_transaction_reset=today)
        
        # Reset limits
        count = wallets.update(
            daily_transaction_total=0,
            daily_transaction_count=0,
            daily_transaction_reset=today
        )
        
        logger.info(f"Reset daily transaction limits for {count} wallets")
        return count
    except Exception as e:
        logger.error(f"Error resetting daily transaction limits: {str(e)}")
        raise


@shared_task
def verify_bank_accounts_task():
    """
    Verify unverified bank accounts (scheduled task)
    """
    # Get models
    BankAccount = apps.get_model('wallet', 'BankAccount')
    
    try:
        # Get wallet service
        wallet_service = WalletService()
        
        # Find unverified bank accounts
        bank_accounts = BankAccount.objects.filter(
            is_verified=False,
            is_active=True
        ).select_related('bank')
        
        count = 0
        for bank_account in bank_accounts:
            try:
                # Verify account details
                account_data = wallet_service.verify_bank_account(
                    bank_account.account_number,
                    bank_account.bank.code
                )
                
                # Update account name if available
                account_name = account_data.get('account_name')
                if account_name:
                    bank_account.account_name = account_name
                    
                # Mark as verified
                bank_account.is_verified = True
                bank_account.save(update_fields=['account_name', 'is_verified'])
                
                # Create transfer recipient if missing
                if not bank_account.paystack_recipient_code:
                    from wallet.services.paystack_service import PaystackService
                    paystack = PaystackService()
                    
                    recipient_data = paystack.create_transfer_recipient(
                        account_type='nuban',
                        name=bank_account.account_name,
                        account_number=bank_account.account_number,
                        bank_code=bank_account.bank.code,
                        currency=get_wallet_setting('CURRENCY')
                    )
                    
                    if recipient_data and 'recipient_code' in recipient_data:
                        bank_account.paystack_recipient_code = recipient_data['recipient_code']
                        bank_account.paystack_data = recipient_data
                        bank_account.save(update_fields=['paystack_recipient_code', 'paystack_data'])
                        
                        # Create transfer recipient record
                        TransferRecipient = apps.get_model('wallet', 'TransferRecipient')
                        TransferRecipient.objects.create(
                            wallet=bank_account.wallet,
                            recipient_code=recipient_data['recipient_code'],
                            type='nuban',
                            name=bank_account.account_name,
                            account_number=bank_account.account_number,
                            bank_code=bank_account.bank.code,
                            bank_name=bank_account.bank.name,
                            currency=get_wallet_setting('CURRENCY'),
                            paystack_data=recipient_data
                        )
                
                count += 1
            except Exception as e:
                logger.error(f"Error verifying bank account {bank_account.id}: {str(e)}")
        
        logger.info(f"Verified {count} bank accounts")
        return count
    except Exception as e:
        logger.error(f"Error verifying bank accounts: {str(e)}")
        raise


@shared_task
def check_expired_cards_task():
    """
    Check for expired cards and mark them as inactive (scheduled task)
    """
    # Get models
    Card = apps.get_model('wallet', 'Card')
    
    try:
        # Get today's date
        now = timezone.now()
        current_month = now.month
        current_year = now.year
        
        # Find expired cards
        expired_cards = Card.objects.filter(
            is_active=True
        ).filter(
            # Cards that expired in previous years
            expiry_year__lt=current_year
        ).union(
            # Cards that expired in previous months of current year
            Card.objects.filter(
                expiry_year=current_year,
                expiry_month__lt=current_month,
                is_active=True
            )
        )
        
        # Mark as inactive
        count = 0
        for card in expired_cards:
            try:
                card.is_active = False
                
                # Clear default status
                if card.is_default:
                    card.is_default = False
                    
                card.save(update_fields=['is_active', 'is_default'])
                
                # Set another card as default if available
                if card.is_default:
                    active_card = Card.objects.filter(
                        wallet=card.wallet,
                        is_active=True
                    ).first()
                    
                    if active_card:
                        active_card.set_as_default()
                
                count += 1
            except Exception as e:
                logger.error(f"Error processing expired card {card.id}: {str(e)}")
        
        logger.info(f"Marked {count} expired cards as inactive")
        return count
    except Exception as e:
        logger.error(f"Error checking expired cards: {str(e)}")
        raise