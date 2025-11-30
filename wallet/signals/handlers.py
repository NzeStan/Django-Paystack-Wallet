import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from django.apps import apps
from wallet.settings import get_wallet_setting
from wallet.services.wallet_service import WalletService
from django.db import transaction



logger = logging.getLogger(__name__)


@receiver(post_save, sender=get_wallet_setting('USER_MODEL'))
def create_wallet_for_user(sender, instance, created, **kwargs):
    """Create a wallet for a new user"""
    if not created:
        return
    
    if not get_wallet_setting('AUTO_CREATE_WALLET'):
        return
    
    try:
        if get_wallet_setting('USE_CELERY'):
            from wallet.tasks import create_wallet_for_user_task
            # ✅ FIX: Wait for transaction to commit before queuing task
            transaction.on_commit(lambda: create_wallet_for_user_task.delay(instance.pk))
        else:
            wallet_service = WalletService()
            wallet_service.get_wallet(instance)
    except Exception as e:
        logger.error(f"Error creating wallet for user {instance.pk}: {str(e)}")



@receiver(post_save)
def update_wallet_on_transaction_change(sender, instance, created, **kwargs):
    """
    Update wallet metrics when a transaction status changes
    
    Args:
        sender: Transaction model
        instance: Transaction instance
        created: Whether the transaction was just created
        **kwargs: Additional arguments
    """
    # Check if this is a Transaction model
    transaction_model = apps.get_model('wallet', 'Transaction')
    if sender != transaction_model:
        return
    
    # Skip if this is a new transaction (handled elsewhere)
    if created:
        return
    
    # Only update metrics for successful transactions
    from wallet.constants import TRANSACTION_STATUS_SUCCESS
    if instance.status != TRANSACTION_STATUS_SUCCESS:
        return
    
    # Update transaction metrics
    try:
        instance.wallet.update_transaction_metrics(instance.amount.amount)
    except Exception as e:
        logger.error(f"Error updating wallet metrics for transaction {instance.pk}: {str(e)}")


@receiver(post_save)
def process_settlement_schedule(sender, instance, created, **kwargs):
    """
    Process settlement schedules when wallet balance changes
    
    OPTIMIZED:
    - Uses get_wallet_setting helper
    - Proper select_related for QuerySet optimization
    - Clean Celery vs sync logic separation
    - Comprehensive error handling
    
    Args:
        sender: Wallet model
        instance: Wallet instance
        created: Whether the wallet was just created
        **kwargs: Additional arguments
    """
    # Check if this is a Wallet model
    wallet_model = apps.get_model('wallet', 'Wallet')
    if sender != wallet_model:
        return
    
    # Skip if this is a new wallet
    if created:
        return
    
    # Skip if auto settlement is disabled
    if not get_wallet_setting('AUTO_SETTLEMENT'):
        logger.debug(
            f"Auto settlement disabled, skipping schedule processing for wallet {instance.id}"
        )
        return
    
    logger.debug(
        f"Checking threshold-based settlement schedules for wallet {instance.id}"
    )
    
    # Process threshold-based settlement schedules
    try:
        # Check if we should use Celery
        if get_wallet_setting('USE_CELERY'):
            # ✅ Process asynchronously with Celery
            from wallet.tasks import process_wallet_settlement_schedules_task
            
            process_wallet_settlement_schedules_task.delay(instance.pk)
            
            logger.debug(
                f"Queued settlement schedule processing task for wallet {instance.pk}"
            )
        else:
            # ✅ Process synchronously with optimized queries
            from wallet.services.settlement_service import SettlementService
            
            settlement_service = SettlementService()
            
            # Get SettlementSchedule model
            schedule_model = apps.get_model('wallet', 'SettlementSchedule')
            
            # ✅ OPTIMIZED: Use select_related to avoid N+1 queries
            schedules = schedule_model.objects.filter(
                wallet=instance,
                is_active=True,
                schedule_type='threshold'
            ).exclude(
                amount_threshold=None
            ).select_related(
                'wallet',
                'wallet__user',
                'bank_account',
                'bank_account__bank'  # ✅ Include bank details
            )
            
            logger.debug(
                f"Found {schedules.count()} active threshold schedules "
                f"for wallet {instance.id}"
            )
            
            for schedule in schedules:
                try:
                    # Check if balance exceeds threshold
                    if instance.balance.amount >= schedule.amount_threshold.amount:
                        # Calculate settlement amount
                        amount = settlement_service._calculate_settlement_amount(schedule)
                        
                        if amount > 0:
                            logger.info(
                                f"Creating threshold settlement for schedule {schedule.id}: "
                                f"amount={amount}"
                            )
                            
                            # Create settlement
                            settlement_service.create_settlement(
                                wallet=instance,
                                bank_account=schedule.bank_account,
                                amount=amount,
                                reason="Automatic threshold-based settlement",
                                metadata={
                                    'schedule_id': str(schedule.id),
                                    'schedule_type': 'threshold',
                                    'threshold': str(schedule.amount_threshold.amount)
                                }
                            )
                            
                            # Update schedule last settlement time
                            schedule.last_settlement = instance.updated_at
                            schedule.save(update_fields=['last_settlement'])
                            
                            logger.info(
                                f"Created settlement for schedule {schedule.id}"
                            )
                except Exception as e:
                    logger.error(
                        f"Error processing schedule {schedule.id}: {str(e)}",
                        exc_info=True
                    )
                    # Continue with other schedules
                    continue
                    
    except Exception as e:
        logger.error(
            f"Error processing settlement schedules for wallet {instance.pk}: {str(e)}",
            exc_info=True
        )



@receiver(post_save)
def create_dedicated_account(sender, instance, created, **kwargs):
    """Create a dedicated virtual account for a wallet"""
    wallet_model = apps.get_model('wallet', 'Wallet')
    if sender != wallet_model:
        return
    
    if created or instance.dedicated_account_number:
        return
    
    if not instance.paystack_customer_code:
        return
    
    try:
        if get_wallet_setting('USE_CELERY'):
            from wallet.tasks import create_dedicated_account_task
            # ✅ FIX: Wait for transaction to commit
            transaction.on_commit(lambda: create_dedicated_account_task.delay(instance.pk))
        else:
            wallet_service = WalletService()
            wallet_service.create_dedicated_account(instance)
    except Exception as e:
        logger.error(f"Error creating dedicated account for wallet {instance.pk}: {str(e)}")