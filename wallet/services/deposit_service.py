"""
Deposits: Paystack checkout, saved-card charges and dedicated virtual accounts.

Flow::

    initialize_deposit()  -> PENDING transaction + Paystack checkout URL
    (customer pays)
    charge.success webhook / verify_deposit() -> process_charge()
        -> wallet credited exactly once, transaction SUCCESS

``process_charge`` is idempotent and locks the transaction row, so duplicate
webhooks, a webhook racing a manual verify, or a retried verify can never
credit a wallet twice.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.conf import wallet_settings
from wallet.constants import (
    DIRECTION_CREDIT,
    FEE_BEARER_CUSTOMER,
    FEE_BEARER_MERCHANT,
    FEE_BEARER_PLATFORM,
    PAYMENT_CHANNEL_LOCAL_CARD,
    PAYMENT_METHOD_CARD,
    PAYMENT_METHOD_DVA,
    PAYSTACK_CHANNEL_TO_PAYMENT_METHOD,
    TRANSACTION_STATUS_CANCELLED,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_TYPE_DEPOSIT,
)
from wallet.exceptions import (
    DuplicateReference,
    InvalidAmount,
    InvalidTransactionState,
    PaystackAPIError,
    WalletError,
)
from wallet.models import Transaction, Wallet
from wallet.services.base import BaseService
from wallet.services.card_service import CardService
from wallet.services.fee_service import (
    FeeCalculationResult,
    get_fee_calculator,
    paystack_channel_to_fee_channel,
)
from wallet.signals import deposit_completed, deposit_failed, deposit_initialized, send_on_commit
from wallet.utils.id_generators import generate_transaction_reference
from wallet.utils.money import from_minor_units, quantize, to_minor_units

logger = logging.getLogger('wallet')

PACKAGE_MARKER = 'django-paystack-wallet'
_TOLERANCE = Decimal('0.01')
PENDING_CHARGE_STATUSES = {'pending', 'ongoing', 'processing', 'queued', 'send_otp', 'send_pin', 'send_phone',
                           'send_birthday', 'send_address', 'open_url', 'pay_offline'}
FAILED_CHARGE_STATUSES = {'failed', 'reversed', 'abandoned'}


class DepositService(BaseService):

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    def initialize_deposit(self, wallet, amount, email=None, callback_url=None, reference=None, metadata=None,
                           channels=None, fee_bearer=None, payment_channel=None, description=None,
                           split_code=None, subaccount=None, ip_address=None, user_agent=None):
        """
        Start a Paystack checkout that funds ``wallet`` with ``amount``.

        Returns ``authorization_url`` (redirect the user there) and
        ``access_code`` (for Paystack InlineJS/Popup), plus the fee breakdown.
        """
        self.require_feature('DEPOSITS')
        wallet.check_active()
        amount = wallet.validate_amount(amount)
        self.check_amount_limits(amount, 'MINIMUM_DEPOSIT_AMOUNT')
        reference = self.validate_reference(reference) or generate_transaction_reference('DEP')

        email = email or getattr(wallet.user, 'email', None)
        if not email:
            raise WalletError(_("An email address is required for Paystack checkout"))

        fee = get_fee_calculator(wallet).calculate(
            amount, TRANSACTION_TYPE_DEPOSIT, payment_channel or PAYMENT_CHANNEL_LOCAL_CARD, bearer=fee_bearer,
        )

        user_metadata = dict(metadata or {})
        try:
            with db_transaction.atomic():
                txn = Transaction.objects.create(
                    wallet=wallet,
                    amount=amount,
                    fees=fee.fee_amount,
                    total_amount=fee.merchant_receives,
                    fee_bearer=fee.bearer,
                    transaction_type=TRANSACTION_TYPE_DEPOSIT,
                    direction=DIRECTION_CREDIT,
                    status=TRANSACTION_STATUS_PENDING,
                    reference=reference,
                    description=description or str(_("Wallet funding")),
                    metadata={**user_metadata, 'fee': fee.to_dict(), 'charge_amount': str(fee.customer_pays.amount)},
                    **self.request_context(ip_address, user_agent),
                )
        except IntegrityError as exc:
            raise DuplicateReference() from exc

        paystack_metadata = {
            **user_metadata,
            'wallet_id': str(wallet.pk),
            'transaction_id': str(txn.pk),
            'source': PACKAGE_MARKER,
            'custom_fields': [
                {'display_name': 'Wallet', 'variable_name': 'wallet_tag', 'value': wallet.tag or str(wallet.pk)},
            ],
        }
        try:
            data = self.paystack.transactions.initialize(
                email=email,
                amount=to_minor_units(fee.customer_pays.amount),
                currency=wallet.currency,
                reference=reference,
                callback_url=callback_url or wallet_settings.DEFAULT_CALLBACK_URL,
                metadata=paystack_metadata,
                channels=channels or wallet_settings.PAYMENT_CHANNELS,
                split_code=split_code,
                subaccount=subaccount,
            )
        except PaystackAPIError as exc:
            self.set_status(txn, TRANSACTION_STATUS_FAILED, reason=f"Paystack initialization failed: {exc.message}")
            send_on_commit(deposit_failed, sender=Transaction, transaction=txn, wallet=wallet, reason=exc.message)
            raise

        txn.paystack_reference = reference
        txn.paystack_response = data
        txn.metadata = {**txn.metadata, 'access_code': data.get('access_code'),
                        'authorization_url': data.get('authorization_url')}
        txn.save(update_fields=['paystack_reference', 'paystack_response', 'metadata', 'updated_at'])

        send_on_commit(
            deposit_initialized, sender=Transaction, transaction=txn, wallet=wallet,
            authorization_url=data.get('authorization_url'), access_code=data.get('access_code'),
        )
        return {
            'authorization_url': data.get('authorization_url'),
            'access_code': data.get('access_code'),
            'reference': reference,
            'transaction_id': str(txn.pk),
            'amount': str(amount.amount),
            'charge_amount': str(fee.customer_pays.amount),
            'currency': wallet.currency,
            'public_key': wallet_settings.PAYSTACK_PUBLIC_KEY,
            'fee_breakdown': fee.to_dict(),
        }

    # Backwards compatible name
    def initialize_card_charge(self, wallet, amount, email=None, reference=None, callback_url=None, metadata=None,
                               payment_channel=PAYMENT_CHANNEL_LOCAL_CARD, is_international=False,
                               fee_bearer=None):
        from wallet.constants import PAYMENT_CHANNEL_INTL_CARD

        return self.initialize_deposit(
            wallet, amount, email=email, reference=reference, callback_url=callback_url, metadata=metadata,
            fee_bearer=fee_bearer,
            payment_channel=PAYMENT_CHANNEL_INTL_CARD if is_international else payment_channel,
        )

    # ------------------------------------------------------------------
    # Saved card charge
    # ------------------------------------------------------------------

    def charge_card(self, card, amount, reference=None, metadata=None, fee_bearer=None, description=None,
                    ip_address=None, user_agent=None):
        """Fund the wallet from a saved card. Returns the deposit Transaction."""
        self.require_feature('DEPOSITS')
        self.require_feature('CARDS')
        wallet = card.wallet
        wallet.check_active()
        CardService(paystack=self.paystack).check_card(card)
        amount = wallet.validate_amount(amount)
        self.check_amount_limits(amount, 'MINIMUM_DEPOSIT_AMOUNT')
        reference = self.validate_reference(reference) or generate_transaction_reference('CHG')

        channel = paystack_channel_to_fee_channel('card', {'country_code': card.country_code})
        fee = get_fee_calculator(wallet).calculate(amount, TRANSACTION_TYPE_DEPOSIT, channel, bearer=fee_bearer)

        txn = Transaction.objects.create(
            wallet=wallet, amount=amount, fees=fee.fee_amount, total_amount=fee.merchant_receives,
            fee_bearer=fee.bearer, transaction_type=TRANSACTION_TYPE_DEPOSIT, direction=DIRECTION_CREDIT,
            status=TRANSACTION_STATUS_PENDING, reference=reference, card=card, payment_method=PAYMENT_METHOD_CARD,
            description=description or str(_("Card top-up")),
            metadata={**(metadata or {}), 'fee': fee.to_dict(), 'charge_amount': str(fee.customer_pays.amount)},
            **self.request_context(ip_address, user_agent),
        )

        try:
            data = self.paystack.transactions.charge_authorization(
                email=card.email or wallet.user.email,
                amount=to_minor_units(fee.customer_pays.amount),
                authorization_code=card.paystack_authorization_code,
                reference=reference,
                currency=wallet.currency,
                metadata={**(metadata or {}), 'wallet_id': str(wallet.pk), 'transaction_id': str(txn.pk),
                          'card_id': str(card.pk), 'source': PACKAGE_MARKER},
            )
        except PaystackAPIError as exc:
            if exc.is_definitive:
                self.set_status(txn, TRANSACTION_STATUS_FAILED, reason=exc.paystack_message or exc.message)
                send_on_commit(deposit_failed, sender=Transaction, transaction=txn, wallet=wallet, reason=exc.message)
                raise
            # Unknown outcome: keep pending; reconciliation or the webhook settles it.
            logger.warning("Card charge %s outcome unknown: %s", reference, exc)
            txn.metadata = {**txn.metadata, 'needs_reconciliation': True}
            txn.save(update_fields=['metadata', 'updated_at'])
            return txn

        return self.process_charge(data) or txn

    # Backwards compatible name
    def charge_saved_card(self, card, amount, reference=None, metadata=None):
        return self.charge_card(card, amount, reference=reference, metadata=metadata)

    # ------------------------------------------------------------------
    # Verification & completion
    # ------------------------------------------------------------------

    def verify_deposit(self, reference):
        """Ask Paystack for the charge status and settle the local transaction (idempotent)."""
        txn = Transaction.objects.filter(reference=reference).first()
        if txn is not None and txn.transaction_type != TRANSACTION_TYPE_DEPOSIT:
            raise InvalidTransactionState(_("Transaction {reference} is not a deposit").format(reference=reference))
        if txn is not None and txn.is_final:
            return txn
        data = self.paystack.transactions.verify(reference)
        return self.process_charge(data)

    verify_transaction = verify_deposit

    def process_charge(self, data, webhook_event=None):
        """
        Settle a charge from Paystack data (``charge.success`` webhook or verify response).

        Returns the deposit Transaction, or None when the charge doesn't belong
        to a wallet (e.g. a checkout your own code started for something else).
        """
        data = data or {}
        reference = data.get('reference')
        if not reference:
            return None
        status = (data.get('status') or '').lower()

        with db_transaction.atomic():
            txn = Transaction.objects.select_for_update().filter(reference=reference).first()
            if txn is None:
                if status != 'success':
                    return None
                txn = self._create_unmatched_deposit(data)
                if txn is None:
                    return None
            elif txn.transaction_type != TRANSACTION_TYPE_DEPOSIT:
                return None

            if webhook_event is not None and webhook_event.transaction_id is None:
                webhook_event.transaction = txn
                webhook_event.save(update_fields=['transaction'])

            if txn.is_final:
                return txn

            if status == 'success':
                self._complete_deposit(txn, data)
            elif status in FAILED_CHARGE_STATUSES:
                if status == 'abandoned' and txn.created_at > timezone.now() - timedelta(hours=24):
                    # The customer may still come back and pay within the session.
                    return txn
                reason = data.get('gateway_response') or data.get('message') or status
                txn.paystack_response = data
                txn.save(update_fields=['paystack_response', 'updated_at'])
                self.set_status(txn, TRANSACTION_STATUS_FAILED, reason=reason)
                send_on_commit(deposit_failed, sender=Transaction, transaction=txn, wallet=txn.wallet, reason=reason)
            else:
                txn.paystack_response = data
                txn.save(update_fields=['paystack_response', 'updated_at'])
        return txn

    def _complete_deposit(self, txn, data):
        """Credit the wallet for a successful charge. Must run inside the row lock."""
        wallet = txn.wallet
        paid = from_minor_units(data.get('amount'))
        currency = (data.get('currency') or wallet.currency).upper()
        channel = (data.get('channel') or '').lower()
        authorization = data.get('authorization') or {}

        txn.paystack_response = data
        txn.paystack_reference = data.get('reference')
        txn.paystack_id = data.get('id')
        txn.channel = channel
        txn.payment_method = PAYSTACK_CHANNEL_TO_PAYMENT_METHOD.get(channel, txn.payment_method)

        if currency != wallet.currency:
            reason = f"Currency mismatch: received {currency}, wallet is {wallet.currency}. Needs manual review."
            logger.error("Deposit %s: %s", txn.reference, reason)
            txn.save()
            # Not raised: raising here would roll back the failed status we just recorded.
            self.set_status(txn, TRANSACTION_STATUS_FAILED, reason=reason)
            send_on_commit(deposit_failed, sender=Transaction, transaction=txn, wallet=wallet, reason=reason)
            return txn

        fee_channel = paystack_channel_to_fee_channel(channel, authorization)
        calculator = get_fee_calculator(wallet)
        bearer = txn.fee_bearer or calculator.get_default_bearer(TRANSACTION_TYPE_DEPOSIT, fee_channel)
        expected_charge = Decimal(str((txn.metadata or {}).get('charge_amount') or txn.amount.amount))

        try:
            actual = calculator.calculate(Money(paid, currency), TRANSACTION_TYPE_DEPOSIT, fee_channel,
                                          bearer=FEE_BEARER_MERCHANT)
            actual_fee = actual.fee_amount.amount
        except InvalidAmount:
            actual_fee = paid

        if bearer == FEE_BEARER_PLATFORM:
            credit, fee = paid, actual_fee
        elif bearer == FEE_BEARER_CUSTOMER and paid + _TOLERANCE >= expected_charge:
            credit = min(txn.amount.amount, paid)
            fee = paid - credit
        else:
            fee = min(actual_fee, paid)
            credit = paid - fee
        credit, fee = quantize(credit), quantize(fee)

        if abs(paid - expected_charge) > _TOLERANCE and txn.card_id is None and channel != 'dedicated_nuban':
            logger.warning("Deposit %s: expected %s, Paystack collected %s", txn.reference, expected_charge, paid)

        txn.fees = Money(fee, currency)
        txn.total_amount = Money(credit, currency)
        txn.metadata = {**(txn.metadata or {}), 'paid_amount': str(paid), 'fee_channel': fee_channel}
        if credit > 0:
            txn.balance_after = wallet.credit(credit, force=True)
        txn.save()
        self.set_status(txn, TRANSACTION_STATUS_SUCCESS)

        if fee > 0:
            try:
                collected = FeeCalculationResult(
                    Money(paid, currency), Money(fee, currency), FEE_BEARER_PLATFORM, TRANSACTION_TYPE_DEPOSIT,
                    fee_channel, details={'bearer': bearer, 'credited': str(credit), 'paid': str(paid)},
                )
                collected.bearer = bearer
                calculator.record_fee_history(txn, collected)
            except InvalidAmount:
                pass

        if channel == 'card' and authorization.get('reusable'):
            card = CardService(paystack=self.paystack).save_card_from_authorization(
                wallet, authorization, (data.get('customer') or {}).get('email'),
            )
            if card is not None and txn.card_id is None:
                txn.card = card
                txn.save(update_fields=['card', 'updated_at'])

        send_on_commit(deposit_completed, sender=Transaction, transaction=txn, wallet=wallet)
        self.after_credit(wallet)
        return txn

    def _create_unmatched_deposit(self, data):
        """
        Money that arrived without a pre-created transaction. Only transfers
        into a wallet's dedicated virtual account are accepted automatically.
        """
        if (data.get('channel') or '').lower() != 'dedicated_nuban':
            return None
        if not wallet_settings.ENABLE_DEDICATED_ACCOUNTS:
            logger.warning("DVA deposit %s received while dedicated accounts are disabled", data.get('reference'))

        wallet = self._wallet_for_dva_charge(data)
        if wallet is None:
            logger.error("DVA deposit %s could not be matched to a wallet", data.get('reference'))
            return None

        paid = from_minor_units(data.get('amount'))
        authorization = data.get('authorization') or {}
        sender = authorization.get('sender_name') or authorization.get('account_name') or ''
        try:
            # Savepoint: a concurrent duplicate webhook may insert the same reference first.
            with db_transaction.atomic():
                return Transaction.objects.create(
                    wallet=wallet,
                    amount=Money(paid, wallet.currency),
                    total_amount=Money(paid, wallet.currency),
                    transaction_type=TRANSACTION_TYPE_DEPOSIT,
                    direction=DIRECTION_CREDIT,
                    status=TRANSACTION_STATUS_PENDING,
                    reference=data['reference'],
                    payment_method=PAYMENT_METHOD_DVA,
                    description=str(_("Bank transfer to dedicated account")) + (f" from {sender}" if sender else ''),
                    metadata={
                        'source': 'dedicated_account',
                        'sender_name': sender,
                        'sender_bank': authorization.get('sender_bank'),
                        'sender_account_number': authorization.get('sender_bank_account_number'),
                        'narration': authorization.get('narration'),
                        'charge_amount': str(paid),
                    },
                )
        except IntegrityError:
            return Transaction.objects.select_for_update().filter(reference=data['reference']).first()

    @staticmethod
    def _wallet_for_dva_charge(data):
        customer = data.get('customer') or {}
        code = customer.get('customer_code')
        if code:
            wallet = Wallet.objects.filter(paystack_customer_code=code).first()
            if wallet:
                return wallet
        authorization = data.get('authorization') or {}
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        account_number = authorization.get('receiver_bank_account_number') or metadata.get('receiver_account_number')
        if account_number:
            return Wallet.objects.filter(dedicated_account_number=account_number).first()
        return None

    # ------------------------------------------------------------------
    # Cancellation & reconciliation
    # ------------------------------------------------------------------

    def cancel_deposit(self, txn, reason=None, performed_by=None):
        """Cancel a deposit the customer never paid. No money moves."""
        with db_transaction.atomic():
            txn = self.lock_transaction(txn)
            if txn.transaction_type != TRANSACTION_TYPE_DEPOSIT or not txn.is_pending:
                raise InvalidTransactionState(_("Only pending deposits can be cancelled"))
            if performed_by is not None:
                txn.metadata = {**(txn.metadata or {}), **self.actor(performed_by)}
                txn.save(update_fields=['metadata', 'updated_at'])
            self.set_status(txn, TRANSACTION_STATUS_CANCELLED, reason=reason or str(_("Cancelled")))
        self.audit('deposit.cancel', performed_by, transaction=txn.reference, reason=reason or '')
        return txn

    def reconcile_pending_deposits(self, older_than_minutes=None, limit=None):
        """
        Verify stale pending deposits with Paystack - the safety net for
        webhooks that never arrived. Returns the number of transactions checked.
        """
        minutes = older_than_minutes if older_than_minutes is not None else wallet_settings.RECONCILE_AFTER_MINUTES
        cutoff = timezone.now() - timedelta(minutes=int(minutes))
        pending = Transaction.objects.filter(
            transaction_type=TRANSACTION_TYPE_DEPOSIT, status=TRANSACTION_STATUS_PENDING, created_at__lte=cutoff,
        ).order_by('created_at')[:limit or int(wallet_settings.RECONCILE_BATCH_SIZE)]

        checked = 0
        for txn in pending:
            checked += 1
            try:
                self.verify_deposit(txn.reference)
            except PaystackAPIError as exc:
                if exc.is_definitive and txn.created_at < timezone.now() - timedelta(hours=24):
                    # Paystack has no record of this reference: the checkout was never opened.
                    self.cancel_deposit(txn, reason=f"Not found on Paystack: {exc.paystack_message}")
                else:
                    logger.warning("Could not verify deposit %s: %s", txn.reference, exc)
            except WalletError as exc:
                logger.warning("Deposit %s needs attention: %s", txn.reference, exc)
        return checked
