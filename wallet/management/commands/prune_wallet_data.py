"""
Delete old operational data (processed webhook events, delivery attempts, expired
idempotency records). Ledger data is never touched. Schedule it daily.

    python manage.py prune_wallet_data
    python manage.py prune_wallet_data --days 30
"""
from django.core.management.base import BaseCommand

from wallet.services.webhook_service import WebhookService


class Command(BaseCommand):
    help = 'Prune old webhook events, delivery attempts and idempotency records'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None,
                            help='Keep this many days of processed webhooks (default WALLET_WEBHOOK_RETENTION_DAYS)')

    def handle(self, *args, **options):
        result = WebhookService.prune(options['days'])
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {result['webhook_events']} webhook event(s), {result['delivery_attempts']} delivery "
            f"attempt(s), {result['idempotency_records']} idempotency record(s)"
        ))
