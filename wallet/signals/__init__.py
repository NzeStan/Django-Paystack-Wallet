"""
Signals - the main extension point of the package.

Connect receivers to react to money movement (send notifications, fulfil
orders, update analytics, ...). Every signal is sent *after* the database
transaction commits, so receivers never see money that could still roll back.

    from django.dispatch import receiver
    from wallet.signals import deposit_completed

    @receiver(deposit_completed)
    def on_deposit(sender, transaction, wallet, **kwargs):
        ...

All transaction signals pass ``transaction`` and ``wallet``; other arguments
are listed next to each signal.
"""
from django.db import transaction as db_transaction
from django.dispatch import Signal

# Wallet lifecycle
wallet_created = Signal()                    # wallet
wallet_locked = Signal()                     # wallet, reason
wallet_unlocked = Signal()                   # wallet

# Deposits
deposit_initialized = Signal()               # transaction, wallet, authorization_url, access_code
deposit_completed = Signal()                 # transaction, wallet
deposit_failed = Signal()                    # transaction, wallet, reason

# Withdrawals to bank
withdrawal_initiated = Signal()              # transaction, wallet, requires_otp
withdrawal_completed = Signal()              # transaction, wallet
withdrawal_failed = Signal()                 # transaction, wallet, reason, reversed (bool)

# Wallet-to-wallet transfers
transfer_completed = Signal()                # transaction (sender leg), wallet (sender), recipient_transaction, recipient_wallet

# Wallet payments (e-commerce / marketplace)
payment_completed = Signal()                 # transaction, wallet, merchant_wallet (may be None), escrow (bool)
payment_released = Signal()                  # transaction, wallet, merchant_wallet, merchant_transaction
payment_cancelled = Signal()                 # transaction, wallet

# Refunds to card and reversals
refund_initiated = Signal()                  # transaction, wallet, original_transaction
refund_completed = Signal()                  # transaction, wallet, original_transaction
refund_failed = Signal()                     # transaction, wallet, original_transaction, reason
transaction_reversed = Signal()              # transaction (the reversal), wallet, original_transaction

# Generic status change (every status transition of every transaction)
transaction_status_changed = Signal()        # transaction, wallet, old_status, new_status

# Payment instruments & Paystack customer
card_saved = Signal()                        # card, wallet, created (bool)
bank_account_added = Signal()                # bank_account, wallet
dedicated_account_assigned = Signal()        # wallet, data
dedicated_account_failed = Signal()          # wallet, data
customer_identification = Signal()           # wallet, success (bool), data

# Settlements
settlement_completed = Signal()              # settlement, wallet
settlement_failed = Signal()                 # settlement, wallet, reason

# Every Paystack webhook (after built-in processing): event, data, webhook_event, handled (bool)
paystack_webhook_received = Signal()

# Disputes (from webhooks): event, data, transaction (may be None)
dispute_event = Signal()


def send_on_commit(signal, sender=None, **kwargs):
    """Send ``signal`` once the current DB transaction commits (immediately if none is open)."""
    db_transaction.on_commit(lambda: signal.send(sender=sender, **kwargs))


__all__ = [name for name, value in dict(globals()).items() if isinstance(value, Signal)] + ['send_on_commit']
