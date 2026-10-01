"""
Sync the Bank table from Paystack.

    python manage.py sync_banks
    python manage.py sync_banks --country ghana --currency GHS
"""
from django.core.management.base import BaseCommand, CommandError

from wallet.exceptions import WalletError
from wallet.models import Bank
from wallet.services.bank_account_service import BankAccountService


class Command(BaseCommand):
    help = 'Sync banks from Paystack (works with or without Celery)'

    def add_arguments(self, parser):
        parser.add_argument('--country', help='Paystack country name, e.g. nigeria, ghana, kenya, south africa')
        parser.add_argument('--currency', help='Currency code, e.g. NGN, GHS')
        parser.add_argument('--no-update', action='store_true', help='Only add new banks')

    def handle(self, *args, **options):
        try:
            created, updated, errors = BankAccountService().sync_banks(
                country=options.get('country'), currency=options.get('currency'),
                force_update=not options['no_update'],
            )
        except WalletError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Created {created}, updated {updated}, errors {errors}. Banks in database: {Bank.objects.count()}"
        ))
