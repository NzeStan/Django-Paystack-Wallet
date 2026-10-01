import logging

from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate, post_save
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger('wallet')


class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wallet'
    verbose_name = _("Wallet")

    def ready(self):
        from wallet import checks  # noqa: F401  (registers system checks)
        from wallet import notifications
        from wallet.signals.handlers import create_wallet_for_user

        post_save.connect(
            create_wallet_for_user, sender=settings.AUTH_USER_MODEL,
            dispatch_uid='wallet.create_wallet_for_user',
        )
        notifications.connect()
        post_migrate.connect(sync_banks_on_first_migrate, sender=self, dispatch_uid='wallet.sync_banks')


def sync_banks_on_first_migrate(sender, **kwargs):
    """Populate banks after the first migrate when ``WALLET_AUTO_SYNC_BANKS`` is on."""
    from wallet.conf import wallet_settings
    from wallet.models import Bank

    if not wallet_settings.AUTO_SYNC_BANKS or not wallet_settings.PAYSTACK_SECRET_KEY:
        return
    try:
        if Bank.objects.exists():
            return
        if wallet_settings.USE_CELERY:
            from wallet.tasks import sync_banks_from_paystack_task
            sync_banks_from_paystack_task.delay()
        else:
            from wallet.services.bank_account_service import BankAccountService
            BankAccountService().sync_banks()
    except Exception as exc:
        logger.warning("Could not auto-sync banks: %s", exc)
