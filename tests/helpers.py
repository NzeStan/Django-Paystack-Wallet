"""Importable helpers referenced by dotted-path settings in tests."""
from decimal import Decimal

from wallet.notifications.backends import BaseNotificationBackend
from wallet.services.fee_service import FeeCalculator


def upper_normalizer(value):
    return str(value).upper()


class FlatTenCalculator(FeeCalculator):
    """Custom pricing: always NGN 10."""

    def is_enabled(self, transaction_type, payment_channel=None):
        return True

    def get_fee(self, amount, transaction_type, payment_channel=None):
        return Decimal('10.00'), 'custom', None, {'rule': 'flat ten'}


class RecordingBackend(BaseNotificationBackend):
    sent = []

    def send(self, event, user, context):
        RecordingBackend.sent.append((event, user.pk, context))


class ExplodingBackend(BaseNotificationBackend):
    def send(self, event, user, context):
        raise RuntimeError('boom')
