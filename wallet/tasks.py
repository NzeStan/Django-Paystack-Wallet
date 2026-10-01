"""
Background tasks.

Celery is optional. With ``WALLET_USE_CELERY = True`` (and Celery installed via
``pip install django-paystack-wallet[celery]``) these run on your workers.
Without Celery the same functions can be called directly, or scheduled with
the management commands (``reconcile_transactions``, ``process_settlements``).

Suggested Celery beat schedule::

    CELERY_BEAT_SCHEDULE = {
        'wallet-reconcile': {'task': 'wallet.tasks.reconcile_transactions_task', 'schedule': 600},
        'wallet-settlements': {'task': 'wallet.tasks.process_due_settlements_task', 'schedule': 900},
        'wallet-webhook-retries': {'task': 'wallet.tasks.retry_failed_webhook_deliveries_task', 'schedule': 900},
        'wallet-expired-cards': {'task': 'wallet.tasks.check_expired_cards_task', 'schedule': 86400},
        'wallet-prune': {'task': 'wallet.tasks.prune_wallet_data_task', 'schedule': 86400},
    }
"""
import logging

from django.contrib.auth import get_user_model

try:  # pragma: no cover - exercised implicitly depending on the environment
    from celery import shared_task
except ImportError:  # pragma: no cover
    import functools

    class _InlineTask:
        """Stand-in for Celery's bound ``self``: retry() just re-raises."""

        def retry(self, exc=None, **kwargs):
            raise exc

    def shared_task(*task_args, **task_kwargs):
        """Fallback when Celery isn't installed: ``.delay()`` runs the function inline."""

        def decorator(func):
            call = functools.partial(func, _InlineTask()) if task_kwargs.get('bind') else func
            wrapper = functools.wraps(func)(lambda *args, **kwargs: call(*args, **kwargs))
            wrapper.delay = wrapper
            wrapper.apply_async = lambda args=(), kwargs=None, **_: wrapper(*args, **(kwargs or {}))
            return wrapper

        if len(task_args) == 1 and callable(task_args[0]) and not task_kwargs:
            return decorator(task_args[0])
        return decorator

logger = logging.getLogger('wallet')


@shared_task
def create_wallet_for_user_task(user_id):
    from wallet.services.wallet_service import WalletService

    user = get_user_model().objects.get(pk=user_id)
    return str(WalletService().get_wallet(user).pk)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def setup_paystack_customer_task(self, wallet_id, create_dedicated_account=False):
    from wallet.exceptions import PaystackAPIError
    from wallet.models import Wallet
    from wallet.services.wallet_service import WalletService

    wallet = Wallet.objects.get(pk=wallet_id)
    service = WalletService()
    try:
        service.ensure_customer(wallet)
        if create_dedicated_account and not wallet.dedicated_account_number:
            service.create_dedicated_account(wallet)
    except PaystackAPIError as exc:
        if exc.is_definitive:
            logger.warning("Paystack setup for wallet %s rejected: %s", wallet_id, exc)
            return False
        raise self.retry(exc=exc)
    return True


@shared_task
def create_dedicated_account_task(wallet_id):
    from wallet.models import Wallet
    from wallet.services.wallet_service import WalletService

    WalletService().create_dedicated_account(Wallet.objects.get(pk=wallet_id))
    return True


@shared_task
def process_webhook_event_task(event_id):
    from wallet.services.webhook_service import WebhookService

    return WebhookService().reprocess_webhook_event(event_id)


@shared_task
def deliver_webhook_task(event_id, endpoint_id):
    from wallet.models import WebhookEndpoint, WebhookEvent
    from wallet.services.webhook_service import WebhookService

    attempt = WebhookService().forward_webhook_to_endpoint(
        WebhookEvent.objects.get(pk=event_id), WebhookEndpoint.objects.get(pk=endpoint_id),
    )
    return attempt.is_success


@shared_task
def retry_failed_webhook_deliveries_task():
    from wallet.services.webhook_service import WebhookService

    return WebhookService().retry_all_failed_deliveries()


@shared_task
def reconcile_transactions_task(older_than_minutes=None):
    """Safety net for missed webhooks: verify stale pending deposits and withdrawals."""
    from wallet.services.transaction_service import TransactionService

    return TransactionService().reconcile(older_than_minutes)


@shared_task
def process_due_settlements_task():
    from wallet.services.settlement_service import SettlementService

    return SettlementService().process_due_settlements()


@shared_task
def process_wallet_settlement_schedules_task(wallet_id):
    from wallet.models import Wallet
    from wallet.services.settlement_service import SettlementService

    return SettlementService().process_threshold_schedules(Wallet.objects.get(pk=wallet_id))


@shared_task
def verify_pending_settlements_task():
    from wallet.constants import SETTLEMENT_STATUS_PENDING, SETTLEMENT_STATUS_PROCESSING
    from wallet.models import Settlement
    from wallet.services.settlement_service import SettlementService

    service = SettlementService()
    checked = 0
    for settlement in Settlement.objects.filter(
        status__in=[SETTLEMENT_STATUS_PENDING, SETTLEMENT_STATUS_PROCESSING], transaction__isnull=False,
    )[:100]:
        try:
            service.verify_settlement(settlement)
            checked += 1
        except Exception:
            logger.exception("Could not verify settlement %s", settlement.pk)
    return checked


@shared_task
def sync_banks_from_paystack_task(force_update=True):
    from wallet.services.bank_account_service import BankAccountService

    created, updated, errors = BankAccountService().sync_banks(force_update=force_update)
    return {'created': created, 'updated': updated, 'errors': errors}


@shared_task
def check_expired_cards_task():
    from wallet.models import Card

    count = 0
    for card in Card.objects.active().expired():
        card.remove()
        count += 1
    return count


@shared_task
def prune_wallet_data_task(retention_days=None):
    """Daily housekeeping: keep operational tables small (ledger data is never pruned)."""
    from wallet.services.webhook_service import WebhookService

    return WebhookService.prune(retention_days)
