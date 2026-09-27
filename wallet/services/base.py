"""Shared building blocks for the wallet services."""
import json
import logging
import re
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.conf import is_feature_enabled, wallet_settings
from wallet.constants import (
    DIRECTION_CREDIT,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_SUCCESS,
)
from wallet.exceptions import (
    DuplicateReference,
    FeatureDisabled,
    InvalidAmount,
    TransactionLimitExceeded,
)
from wallet.models import Transaction, Wallet
from wallet.paystack import get_paystack_client
from wallet.signals import send_on_commit, transaction_status_changed
from wallet.utils.money import to_decimal

logger = logging.getLogger('wallet')

_REFERENCE_RE = re.compile(r'^[A-Za-z0-9._=-]{6,100}$')
_TRANSFER_REFERENCE_RE = re.compile(r'^[a-z0-9_-]{16,50}$')


class BaseService:
    """Base class giving every service a Paystack client and common guards."""

    def __init__(self, paystack=None):
        self._paystack = paystack

    @property
    def paystack(self):
        if self._paystack is None:
            self._paystack = get_paystack_client()
        return self._paystack

    @paystack.setter
    def paystack(self, client):
        self._paystack = client

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def require_feature(feature):
        if not is_feature_enabled(feature):
            raise FeatureDisabled(
                _("{feature} are disabled on this platform").format(feature=feature.replace('_', ' ').lower())
            )

    @staticmethod
    def validate_reference(reference, transfer=False):
        """Validate a caller-supplied reference and make sure it is unused."""
        if reference is None:
            return None
        reference = str(reference).strip()
        pattern = _TRANSFER_REFERENCE_RE if transfer else _REFERENCE_RE
        if not pattern.match(reference):
            hint = ('16-50 lowercase letters, digits, "-" or "_"' if transfer
                    else '6-100 letters, digits, ".", "-", "=" or "_"')
            raise InvalidAmount(message=_("Invalid reference: use {hint}").format(hint=hint))
        if Transaction.objects.filter(reference=reference).exists():
            raise DuplicateReference()
        return reference

    @staticmethod
    def check_amount_limits(amount, minimum_setting=None):
        """Per-transaction minimum/maximum checks on the principal amount (Decimal)."""
        amount = to_decimal(amount)
        minimum = wallet_settings.get(minimum_setting) if minimum_setting else None
        global_minimum = wallet_settings.MINIMUM_TRANSACTION_AMOUNT
        for limit in (minimum, global_minimum):
            if limit is not None and amount < Decimal(str(limit)):
                raise InvalidAmount(message=_("The minimum amount is {limit}").format(limit=limit))
        maximum = wallet_settings.MAXIMUM_TRANSACTION_AMOUNT
        if maximum is not None and amount > Decimal(str(maximum)):
            raise TransactionLimitExceeded(_("The maximum amount per transaction is {limit}").format(limit=maximum))
        return amount

    @staticmethod
    def check_daily_limit(locked_wallet, outgoing_total):
        """Call with the wallet row locked so concurrent requests can't race past the limit."""
        limit = locked_wallet.get_daily_limit()
        if limit is None:
            return
        spent = locked_wallet.get_daily_outgoing_total()
        if spent + to_decimal(outgoing_total) > limit:
            remaining = max(limit - spent, Decimal('0'))
            raise TransactionLimitExceeded(
                _("Daily limit of {limit} exceeded. You can still send {remaining} today").format(
                    limit=limit, remaining=remaining
                )
            )

    # ------------------------------------------------------------------
    # Ledger helpers
    # ------------------------------------------------------------------

    @staticmethod
    def lock_wallet(wallet):
        return Wallet.objects.select_for_update().get(pk=wallet.pk)

    @staticmethod
    def lock_wallets(*wallets):
        """Lock several wallets in primary-key order (prevents deadlocks)."""
        ordered = sorted({w.pk for w in wallets}, key=str)
        locked = {w.pk: w for w in Wallet.objects.select_for_update().filter(pk__in=ordered).order_by('pk')}
        return [locked[w.pk] for w in wallets]

    @staticmethod
    def lock_transaction(transaction):
        return Transaction.objects.select_for_update().select_related('wallet').get(pk=transaction.pk)

    @staticmethod
    def money(amount, currency):
        return Money(to_decimal(amount), currency)

    @staticmethod
    def set_status(txn, new_status, reason=None, save=True, extra_fields=()):
        """Change a transaction's status, stamping completion time and emitting signals."""
        old_status = txn.status
        txn.status = new_status
        fields = {'status', 'updated_at', *extra_fields}
        if new_status in (TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED) or txn.is_final:
            txn.completed_at = txn.completed_at or timezone.now()
            fields.add('completed_at')
        if reason is not None:
            txn.failed_reason = str(reason)[:2000]
            fields.add('failed_reason')
        if save:
            txn.save(update_fields=list(fields))
        if old_status != new_status:
            send_on_commit(
                transaction_status_changed, sender=Transaction, transaction=txn, wallet=txn.wallet,
                old_status=old_status, new_status=new_status,
            )
        return txn

    @staticmethod
    def after_credit(wallet):
        """Hook run after money lands in a wallet (threshold settlements)."""
        if not (wallet_settings.AUTO_SETTLEMENT and is_feature_enabled('SETTLEMENTS')):
            return
        wallet_pk = wallet.pk

        def _run():
            try:
                if wallet_settings.USE_CELERY:
                    from wallet.tasks import process_wallet_settlement_schedules_task
                    process_wallet_settlement_schedules_task.delay(str(wallet_pk))
                else:
                    from wallet.services.settlement_service import SettlementService
                    SettlementService().process_threshold_schedules(Wallet.objects.get(pk=wallet_pk))
            except Exception:
                logger.exception("Threshold settlement processing failed for wallet %s", wallet_pk)

        db_transaction.on_commit(_run)

    @staticmethod
    def audit(action, performed_by=None, **details):
        """
        Record a sensitive action in the ``WALLET_AUDIT_LOGGER`` log (default ``wallet.audit``).
        Route that logger to durable storage (file, SIEM, ...) in your LOGGING config.
        """
        actor = getattr(performed_by, 'pk', performed_by)
        payload = {'action': action, 'performed_by': str(actor) if actor is not None else None,
                   **{key: str(value) for key, value in details.items()}}
        logging.getLogger(wallet_settings.AUDIT_LOGGER).info(json.dumps(payload, sort_keys=True))

    @staticmethod
    def actor(performed_by):
        actor = getattr(performed_by, 'pk', performed_by)
        return {'performed_by': str(actor)} if actor is not None else {}

    @staticmethod
    def request_context(ip_address=None, user_agent=None):
        return {'ip_address': ip_address or None, 'user_agent': (user_agent or '')[:1000]}

    @staticmethod
    def is_credit(txn):
        return txn.direction == DIRECTION_CREDIT
