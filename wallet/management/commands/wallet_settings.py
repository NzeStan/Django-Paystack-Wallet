"""
Print the wallet settings as resolved from Django settings, the environment
and defaults (secret keys are masked). Useful to debug .env configuration.

    python manage.py wallet_settings
"""
import json

from django.core.management.base import BaseCommand

from wallet.conf import setting_name, wallet_settings


class Command(BaseCommand):
    help = 'Show resolved django-paystack-wallet settings'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Output JSON')

    def handle(self, *args, **options):
        resolved = wallet_settings.as_dict()
        if options['json']:
            self.stdout.write(json.dumps({setting_name(k): v for k, v in resolved.items()}, default=str, indent=2))
            return
        width = max(len(setting_name(name)) for name in resolved)
        for name, value in resolved.items():
            self.stdout.write(f"{setting_name(name).ljust(width)}  {value!r}")
