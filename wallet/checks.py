"""System checks (``manage.py check``) that catch misconfiguration early."""
from decimal import Decimal

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from wallet.conf import wallet_settings
from wallet.constants import FEE_BEARERS

VALID_BEARERS = {choice for choice, _label in FEE_BEARERS}


@register(Tags.compatibility)
def check_wallet_settings(app_configs, **kwargs):
    messages = []
    secret = wallet_settings.PAYSTACK_SECRET_KEY or ''

    if not secret:
        messages.append(Warning(
            'PAYSTACK_SECRET_KEY is not set.',
            hint='Set it in your settings or environment; Paystack calls and webhook verification will fail.',
            id='wallet.W001',
        ))
    elif not secret.startswith(('sk_test_', 'sk_live_')):
        messages.append(Warning('PAYSTACK_SECRET_KEY does not look like a Paystack secret key.', id='wallet.W002'))

    if secret.startswith('sk_live_') and getattr(settings, 'DEBUG', False):
        messages.append(Warning('A live Paystack key is configured while DEBUG=True.', id='wallet.W003'))

    public = wallet_settings.PAYSTACK_PUBLIC_KEY or ''
    if secret and public and secret[:8].replace('sk_', 'pk_') != public[:8]:
        messages.append(Warning('PAYSTACK_PUBLIC_KEY and PAYSTACK_SECRET_KEY are from different modes.',
                                id='wallet.W004'))

    if 'rest_framework' not in settings.INSTALLED_APPS:
        messages.append(Error("'rest_framework' must be in INSTALLED_APPS to use the wallet API.", id='wallet.E001'))

    if wallet_settings.USE_CELERY:
        try:
            import celery  # noqa: F401  (availability check)
        except ImportError:
            messages.append(Error('WALLET_USE_CELERY is True but Celery is not installed.',
                                  hint="pip install 'django-paystack-wallet[celery]'", id='wallet.E002'))

    for name in ('DEFAULT_FEE_BEARER', 'DEPOSIT_FEE_BEARER', 'WITHDRAWAL_FEE_BEARER', 'TRANSFER_FEE_BEARER',
                 'PAYMENT_FEE_BEARER', 'DVA_FEE_BEARER'):
        value = wallet_settings.get(name)
        if value and value not in VALID_BEARERS:
            messages.append(Error(f"WALLET_{name}={value!r} is not one of {sorted(VALID_BEARERS)}.",
                                  id='wallet.E003'))

    split = Decimal(str(wallet_settings.FEE_SPLIT_CUSTOMER_PERCENTAGE)) + Decimal(
        str(wallet_settings.FEE_SPLIT_MERCHANT_PERCENTAGE))
    if split != 100:
        messages.append(Error('WALLET_FEE_SPLIT_CUSTOMER_PERCENTAGE + WALLET_FEE_SPLIT_MERCHANT_PERCENTAGE '
                              'must equal 100.', id='wallet.E004'))

    lookups = set(wallet_settings.TRANSFER_RECIPIENT_LOOKUP_FIELDS or [])
    unknown = lookups - {'id', 'tag', 'phone_number', 'email'}
    if unknown:
        messages.append(Error(f"Unknown WALLET_TRANSFER_RECIPIENT_LOOKUP_FIELDS: {sorted(unknown)}",
                              id='wallet.E005'))

    for name in ('FEE_CALCULATOR', 'PHONE_NUMBER_NORMALIZER'):
        try:
            wallet_settings.import_from(name)
        except Exception as exc:
            messages.append(Error(str(exc), id='wallet.E006'))
    try:
        wallet_settings.import_list('NOTIFICATION_BACKENDS')
    except Exception as exc:
        messages.append(Error(f"WALLET_NOTIFICATION_BACKENDS: {exc}", id='wallet.E007'))

    return messages
