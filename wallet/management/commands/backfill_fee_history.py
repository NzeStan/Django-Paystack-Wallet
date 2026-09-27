"""Create FeeHistory rows for transactions with fees but no history (e.g. imported data)."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from wallet.models import FeeHistory, Transaction


class Command(BaseCommand):
    help = 'Backfill fee history for transactions that have fees'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        missing = Transaction.objects.filter(fee_history__isnull=True, fees__gt=0)
        total = missing.count()
        self.stdout.write(f"Found {total} transaction(s) without fee history")
        if options['dry_run']:
            return
        created = 0
        for txn in missing.iterator():
            FeeHistory.objects.create(
                transaction=txn, calculation_method='backfill', original_amount=txn.amount,
                calculated_fee=txn.fees, fee_bearer=txn.fee_bearer or 'platform',
                calculation_details={'backfilled': True, 'backfill_date': timezone.now().isoformat(),
                                     'transaction_type': txn.transaction_type},
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} fee history record(s)"))
