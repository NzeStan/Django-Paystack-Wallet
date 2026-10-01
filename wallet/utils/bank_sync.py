"""Bank synchronisation helpers (work with or without Celery)."""
import logging

logger = logging.getLogger('wallet')


def sync_banks_from_paystack(force_update=True, country=None, currency=None):
    """Fetch Paystack's bank list into the Bank table. Returns (created, updated, errors)."""
    from wallet.services.bank_account_service import BankAccountService

    return BankAccountService().sync_banks(country=country, currency=currency, force_update=force_update)


def ensure_banks_exist():
    """Sync banks if the table is empty. Returns True when banks are available."""
    from wallet.models import Bank

    if Bank.objects.exists():
        return True
    try:
        sync_banks_from_paystack()
    except Exception as exc:
        logger.warning("Could not sync banks: %s", exc)
    return Bank.objects.exists()


def get_bank_by_code(code, currency=None):
    from wallet.models import Bank

    return Bank.objects.get_by_code(code, currency)
