"""
Management command to sync banks from Paystack

Usage:
    python manage.py sync_banks
    python manage.py sync_banks --force
"""
from django.core.management.base import BaseCommand
from wallet.utils.bank_sync import sync_banks_from_paystack
from wallet.models import Bank


class Command(BaseCommand):
    help = 'Sync banks from Paystack (works with or without Celery)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update existing banks',
        )

    def handle(self, *args, **options):
        force = options['force']
        
        self.stdout.write(
            self.style.WARNING('Syncing banks from Paystack...')
        )
        
        try:
            created, updated, errors = sync_banks_from_paystack(force_update=force)
            
            self.stdout.write(self.style.SUCCESS(
                f'\n✅ Sync complete!\n'
                f'   Created: {created}\n'
                f'   Updated: {updated}\n'
                f'   Errors:  {errors}\n'
                f'   Total banks in DB: {Bank.objects.count()}'
            ))
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error: {str(e)}')
            )
            raise