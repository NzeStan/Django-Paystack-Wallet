"""
Pluggable notifications driven by wallet signals.

Nothing is sent unless ``WALLET_NOTIFICATION_BACKENDS`` is configured. See
:mod:`wallet.notifications.backends` for writing your own backend.
"""
import logging

from wallet.conf import wallet_settings
from wallet import signals

logger = logging.getLogger('wallet.notifications')


def get_backends():
    backends = []
    for backend_class in wallet_settings.import_list('NOTIFICATION_BACKENDS'):
        backends.append(backend_class() if isinstance(backend_class, type) else backend_class)
    return backends


def notify(event, user, **context):
    """Send ``event`` to ``user`` through every configured backend. Never raises."""
    if user is None:
        return
    for backend in get_backends():
        if not backend.handles(event):
            continue
        try:
            backend.send(event, user, context)
        except Exception:
            logger.exception("Notification backend %s failed for %s", type(backend).__name__, event)


def _txn_context(transaction, wallet):
    return {
        'transaction': transaction,
        'wallet': wallet,
        'amount': transaction.amount,
        'total_amount': transaction.total_amount,
        'fees': transaction.fees,
        'reference': transaction.reference,
        'balance': wallet.balance if wallet is not None else None,
        'description': transaction.description,
    }


def _on_deposit_completed(sender, transaction, wallet, **kwargs):
    notify('deposit_completed', wallet.user, **_txn_context(transaction, wallet))


def _on_deposit_failed(sender, transaction, wallet, reason=None, **kwargs):
    notify('deposit_failed', wallet.user, reason=reason, **_txn_context(transaction, wallet))


def _on_withdrawal_completed(sender, transaction, wallet, **kwargs):
    notify('withdrawal_completed', wallet.user, **_txn_context(transaction, wallet))


def _on_withdrawal_failed(sender, transaction, wallet, reason=None, **kwargs):
    notify('withdrawal_failed', wallet.user, reason=reason, **_txn_context(transaction, wallet))


def _on_transfer_completed(sender, transaction, wallet, recipient_transaction, recipient_wallet, **kwargs):
    notify('transfer_sent', wallet.user, recipient=recipient_wallet, **_txn_context(transaction, wallet))
    notify('transfer_received', recipient_wallet.user, sender_wallet=wallet,
           **_txn_context(recipient_transaction, recipient_wallet))


def _on_payment_completed(sender, transaction, wallet, **kwargs):
    notify('payment_made', wallet.user, **_txn_context(transaction, wallet))


def _on_payment_released(sender, transaction, wallet, merchant_wallet, merchant_transaction, **kwargs):
    notify('payment_received', merchant_wallet.user, payer_wallet=wallet,
           **_txn_context(merchant_transaction, merchant_wallet))


def _on_payment_cancelled(sender, transaction, wallet, **kwargs):
    notify('payment_cancelled', wallet.user, **_txn_context(transaction, wallet))


def _on_refund_completed(sender, transaction, wallet, **kwargs):
    notify('refund_completed', wallet.user, **_txn_context(transaction, wallet))


def _on_refund_failed(sender, transaction, wallet, reason=None, **kwargs):
    notify('refund_failed', wallet.user, reason=reason, **_txn_context(transaction, wallet))


def _on_dva_assigned(sender, wallet, **kwargs):
    notify('dedicated_account_assigned', wallet.user, wallet=wallet,
           account_number=wallet.dedicated_account_number, bank_name=wallet.dedicated_account_bank,
           account_name=wallet.dedicated_account_name)


def _on_settlement_completed(sender, settlement, wallet, **kwargs):
    notify('settlement_completed', wallet.user, settlement=settlement, wallet=wallet, amount=settlement.amount,
           reference=settlement.reference)


def _on_settlement_failed(sender, settlement, wallet, reason=None, **kwargs):
    notify('settlement_failed', wallet.user, settlement=settlement, wallet=wallet, amount=settlement.amount,
           reference=settlement.reference, reason=reason)


def _on_wallet_locked(sender, wallet, reason='', **kwargs):
    notify('wallet_locked', wallet.user, wallet=wallet, reason=reason)


_CONNECTIONS = (
    (signals.deposit_completed, _on_deposit_completed),
    (signals.deposit_failed, _on_deposit_failed),
    (signals.withdrawal_completed, _on_withdrawal_completed),
    (signals.withdrawal_failed, _on_withdrawal_failed),
    (signals.transfer_completed, _on_transfer_completed),
    (signals.payment_completed, _on_payment_completed),
    (signals.payment_released, _on_payment_released),
    (signals.payment_cancelled, _on_payment_cancelled),
    (signals.refund_completed, _on_refund_completed),
    (signals.refund_failed, _on_refund_failed),
    (signals.dedicated_account_assigned, _on_dva_assigned),
    (signals.settlement_completed, _on_settlement_completed),
    (signals.settlement_failed, _on_settlement_failed),
    (signals.wallet_locked, _on_wallet_locked),
)


def connect():
    """Connect notification receivers (idempotent). Called from ``WalletConfig.ready``."""
    for signal, receiver in _CONNECTIONS:
        signal.connect(receiver, dispatch_uid=f'wallet.notifications.{receiver.__name__}')


def disconnect():
    for signal, receiver in _CONNECTIONS:
        signal.disconnect(dispatch_uid=f'wallet.notifications.{receiver.__name__}')
