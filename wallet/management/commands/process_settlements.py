"""
Run due scheduled settlements (daily / weekly / monthly payouts).

    python manage.py process_settlements
"""
from django.core.management.base import BaseCommand

from wallet.services.settlement_service import SettlementService


class Command(BaseCommand):
    help = 'Process due settlement schedules'

    def handle(self, *args, **options):
        count = SettlementService().process_due_settlements()
        self.stdout.write(self.style.SUCCESS(f"Created {count} settlement(s)"))
