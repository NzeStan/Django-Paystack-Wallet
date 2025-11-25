from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wallet'
    verbose_name = _("Wallet")
    
    def ready(self):
        """Initialize the wallet app"""
        # Import signals
        from wallet.signals import handlers  # noqa
        
        # Optional: Auto-sync banks on first migration
        auto_sync_banks = getattr(settings, 'WALLET_AUTO_SYNC_BANKS', False)
        
        if auto_sync_banks:
            from django.db.models.signals import post_migrate
            post_migrate.connect(
                sync_banks_on_first_migrate,
                sender=self
            )


def sync_banks_on_first_migrate(sender, **kwargs):
    """Auto-sync banks after migrations (if no banks exist)"""
    from wallet.models import Bank
    from wallet.utils.bank_sync import ensure_banks_exist
    from wallet.settings import get_wallet_setting
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Only sync if no banks exist
    if Bank.objects.exists():
        return
    
    logger.info("No banks found, attempting auto-sync from Paystack...")
    
    try:
        if get_wallet_setting('USE_CELERY'):
            from wallet.tasks import sync_banks_from_paystack_task
            sync_banks_from_paystack_task.delay()
            logger.info("Bank sync task queued")
        else:
            success = ensure_banks_exist()
            if success:
                logger.info("Banks auto-synced successfully")
                
    except Exception as e:
        logger.warning(f"Could not auto-sync banks: {str(e)}")