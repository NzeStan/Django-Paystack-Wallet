"""
How an app reacts to the wallet: signals.

These keep orders in sync no matter who acts - the buyer in this UI, staff in the
admin, or the REST API (e.g. POST /wallet/api/transactions/{id}/release/).
"""
import logging

from django.dispatch import receiver

from wallet.signals import deposit_completed, payment_cancelled, payment_released

logger = logging.getLogger('wallet')


@receiver(payment_released)
def complete_order(sender, transaction, **kwargs):
    from shop.models import Order
    Order.objects.filter(payment=transaction).update(status=Order.STATUS_COMPLETED)


@receiver(payment_cancelled)
def refund_order(sender, transaction, **kwargs):
    from shop.models import Order
    Order.objects.filter(payment=transaction).update(status=Order.STATUS_REFUNDED)


@receiver(deposit_completed)
def announce_deposit(sender, transaction, wallet, **kwargs):
    logger.info("[demo] deposit_completed signal: %s credited %s", wallet.tag, transaction.total_amount)
