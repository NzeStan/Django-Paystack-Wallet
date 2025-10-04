import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from django.apps import apps
from wallet.settings import get_wallet_setting
from wallet.services.wallet_service import WalletService


logger = logging.getLogger(__name__)


@receiver(post_save, sender=get_wallet_setting('USER_MODEL'))
def create_wallet_for_user(sender, instance, created, **kwargs):
    """
    Create a wallet for a new user
    
    Args:
        sender: User model
        instance: User instance
        created: Whether the user was just created
        **kwargs: Additional arguments
    """
    # Only create wallet for newly created users
    if not created:
        return
    
    # Check if auto-create is enabled in settings
    if not get_wallet_setting('AUTO_CREATE_WALLET'):
        return
    
    try:
        # Create wallet asynchronously if Celery is available
        if get_wallet_setting('USE_CELERY'):
            from wallet.tasks import create_wallet_for_user_task
            create_wallet_for_user_task.delay(instance.pk)
        else:
            # Create wallet synchronously
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
    Process settlement schedule when a wallet balance changes
    
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
        return
    
    # Process threshold-based settlement schedules
    try:
        # Only process if we have Celery available
        if get_wallet_setting('USE_CELERY'):
            from wallet.tasks import process_wallet_settlement_schedules_task
            process_wallet_settlement_schedules_task.delay(instance.pk)
        else:
            # Process synchronously
            from wallet.services.settlement_service import SettlementService
            settlement_service = SettlementService()
            
            # Find threshold schedules for this wallet
            schedule_model = apps.get_model('wallet', 'SettlementSchedule')
            schedules = schedule_model.objects.filter(
                wallet=instance,
                is_active=True,
                schedule_type='threshold'
            ).exclude(
                amount_threshold=None
            ).select_related('bank_account')
            
            for schedule in schedules:
                # Check if balance exceeds threshold
                if instance.balance.amount >= schedule.amount_threshold.amount:
                    amount = settlement_service._calculate_settlement_amount(schedule)
                    
                    if amount > 0:
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
                        
                        # Update last settlement date
                        schedule.last_settlement = instance.updated_at
                        schedule.save(update_fields=['last_settlement'])
    except Exception as e:
        logger.error(f"Error processing settlement schedules for wallet {instance.pk}: {str(e)}")


@receiver(post_save)
def create_dedicated_account(sender, instance, created, **kwargs):
    """
    Create a dedicated virtual account for a wallet
    
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
    
    # Only process for existing wallets without a dedicated account
    if created or instance.dedicated_account_number:
        return
    
    # Skip if Paystack customer code is not set
    if not instance.paystack_customer_code:
        return
    
    try:
        # Create dedicated account asynchronously if Celery is available
        if get_wallet_setting('USE_CELERY'):
            from wallet.tasks import create_dedicated_account_task
            create_dedicated_account_task.delay(instance.pk)
        else:
            # Create dedicated account synchronously
            wallet_service = WalletService()
            wallet_service.create_dedicated_account(instance)
    except Exception as e:
        logger.error(f"Error creating dedicated account for wallet {instance.pk}: {str(e)}")