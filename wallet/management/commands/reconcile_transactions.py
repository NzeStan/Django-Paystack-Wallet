"""
Verify stale pending deposits and withdrawals with Paystack - the safety net
for webhooks that never arrived. Schedule it (cron / Celery beat) every few minutes.

    python manage.py reconcile_transactions --older-than 10
"""
from django.core.management.base import BaseCommand

from wallet.services.transaction_service import TransactionService


class Command(BaseCommand):
    help = 'Reconcile pending deposits and withdrawals with Paystack'

    def add_arguments(self, parser):
        parser.add_argument('--older-than', type=int, default=None,
                            help='Only transactions pending for at least this many minutes')

    def handle(self, *args, **options):
        result = TransactionService().reconcile(options['older_than'])
        self.stdout.write(self.style.SUCCESS(
            f"Checked {result['deposits']} deposit(s) and {result['withdrawals']} withdrawal(s)"
        ))
