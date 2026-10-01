"""Retry failed deliveries to your registered webhook endpoints."""
from django.core.management.base import BaseCommand

from wallet.services.webhook_service import WebhookService


class Command(BaseCommand):
    help = 'Retry failed outbound webhook deliveries'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        count = WebhookService().retry_all_failed_deliveries(limit=options['limit'])
        self.stdout.write(self.style.SUCCESS(f"Retried {count} delivery(ies)"))
