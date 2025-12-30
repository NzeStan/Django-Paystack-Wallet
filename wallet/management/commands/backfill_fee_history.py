from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from wallet.models import Transaction
from wallet.models.fee_config import FeeHistory
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill fee history for all transactions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of transactions to process in each batch'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate the backfill without making changes'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        
        # Find transactions without fee history
        transactions = Transaction.objects.filter(
            fee_history__isnull=True,
            fees__gt=0
        )
        
        total = transactions.count()
        self.stdout.write(f"Found {total} transactions to backfill")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
            return
        
        created = 0
        errors = 0
        
        # Process in batches
        for i in range(0, total, batch_size):
            batch = transactions[i:i + batch_size]
            
            with db_transaction.atomic():
                for txn in batch:
                    try:
                        FeeHistory.objects.create(
                            transaction=txn,
                            calculation_method='backfill',
                            original_amount=txn.amount,
                            calculated_fee=txn.fees,
                            fee_bearer=txn.fee_bearer or 'platform',
                            calculation_details={
                                'backfilled': True,
                                'backfill_date': timezone.now().isoformat(),
                                'transaction_type': txn.transaction_type,
                            }
                        )
                        created += 1
                        
                    except Exception as e:
                        errors += 1
                        logger.error(f"Error backfilling {txn.id}: {str(e)}")
            
            self.stdout.write(f"Processed {min(i + batch_size, total)}/{total}")
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nBackfill complete: {created} created, {errors} errors"
            )
        )
