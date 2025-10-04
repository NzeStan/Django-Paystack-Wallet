from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WalletConfig(AppConfig):
    name = 'wallet'
    verbose_name = _("Wallet System")
    
    def ready(self):
        # Import signal handlers to register them
        import wallet.signals.handlers