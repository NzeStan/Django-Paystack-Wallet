"""
Create demo users, starting balances and products (safe to run repeatedly).

    python manage.py seed_demo
    python manage.py seed_demo --no-banks

All demo users (including ``admin``) get the same password: the value of the
``DEMO_PASSWORD`` environment variable, or a freshly generated one. It is printed
at the end. No password is stored in the code.
"""
import os
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string

from shop.models import Product
from wallet.conf import wallet_settings
from wallet.exceptions import WalletError
from wallet.models import Transaction
from wallet.services import WalletService

USERS = [
    # username, first, last, phone, starting balance
    ('ada', 'Ada', 'Obi', '08031111111', Decimal('50000')),
    ('bola', 'Bola', 'Ade', '08032222222', Decimal('50000')),
    ('seller', 'Sam', 'Seller', '08033333333', Decimal('0')),
]
PRODUCTS = [
    ('Wireless earbuds', 'Bluetooth 5.3, 24h battery', Decimal('15000')),
    ('Ankara tote bag', 'Handmade, lined', Decimal('7500')),
    ('Phone case', 'Shockproof, clear', Decimal('2500')),
]


class Command(BaseCommand):
    help = 'Seed the demo with users, wallet balances and products'

    def add_arguments(self, parser):
        parser.add_argument('--no-banks', action='store_true', help="Don't sync banks from Paystack")
        parser.add_argument('--password', help='Password for every demo user (default: $DEMO_PASSWORD or random)')

    def handle(self, *args, **options):
        User = get_user_model()
        service = WalletService()
        password = options.get('password') or os.environ.get('DEMO_PASSWORD') or get_random_string(12)

        admin, created = User.objects.get_or_create(
            username='admin', defaults={'email': 'admin@example.com', 'is_staff': True, 'is_superuser': True},
        )
        admin.set_password(password)
        admin.save()
        self.stdout.write(f"admin (staff) {'created' if created else 'updated'}")

        for username, first, last, phone, balance in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@example.com', 'first_name': first, 'last_name': last},
            )
            user.set_password(password)
            user.save()
            wallet = service.get_wallet(user)
            if not wallet.phone_number:
                try:
                    service.set_phone_number(wallet, phone)
                except WalletError as exc:
                    self.stderr.write(f"{username}: phone not set ({exc.message})")
            already_seeded = Transaction.objects.filter(wallet=wallet, metadata__demo_seed=True).exists()
            if balance and not already_seeded:
                service.credit_wallet(wallet, balance, description='Demo starting balance',
                                      transaction_type='commission', metadata={'demo_seed': True})
            wallet.refresh_from_db()
            self.stdout.write(f"{username:<7} @{wallet.tag}  {wallet.phone_number}  {wallet.balance}")

        seller = User.objects.get(username='seller')
        for name, description, price in PRODUCTS:
            Product.objects.get_or_create(seller=seller, name=name,
                                          defaults={'description': description, 'price': price})
        self.stdout.write(f"{Product.objects.count()} products listed")
        self.stdout.write(self.style.SUCCESS(
            f"\nLog in as ada, bola, seller or admin with password: {password}\n"
            "(set DEMO_PASSWORD in demo/.env to choose your own)"
        ))

        if options['no_banks']:
            return
        key = wallet_settings.PAYSTACK_SECRET_KEY or ''
        if not key.startswith('sk_') or 'xxxx' in key:
            self.stdout.write(self.style.WARNING('Paystack keys not set: skipped bank sync (add them to demo/.env)'))
            return
        try:
            created_banks, updated, errors = service.sync_banks()
            self.stdout.write(f"Banks synced: {created_banks} new, {updated} updated, {errors} errors")
        except WalletError as exc:
            self.stdout.write(self.style.WARNING(f"Bank sync failed: {exc.message}"))
        self.stdout.write(self.style.SUCCESS('Demo ready: python manage.py runserver'))
