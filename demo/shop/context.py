from wallet.conf import is_feature_enabled, wallet_settings


def demo_context(request):
    secret = wallet_settings.PAYSTACK_SECRET_KEY or ''
    if secret.startswith('sk_test_') and 'xxxx' not in secret:
        mode = 'test'
    elif secret.startswith('sk_live_'):
        mode = 'live'
    else:
        mode = 'missing'
    return {
        'paystack_mode': mode,
        'require_pin': bool(wallet_settings.REQUIRE_TRANSACTION_PIN),
        'features': {
            name.lower(): is_feature_enabled(name)
            for name in ('DEPOSITS', 'WITHDRAWALS', 'INTERNAL_TRANSFERS', 'PAYMENTS', 'CARDS',
                         'DEDICATED_ACCOUNTS', 'SETTLEMENTS')
        },
    }
