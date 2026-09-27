"""
Exceptions raised by the wallet package.

Every exception derives from :class:`WalletError` and carries an HTTP
``status_code`` and a machine-readable ``code`` so API layers (ours or yours)
can turn them into consistent responses.
"""
from django.utils.translation import gettext_lazy as _


class WalletError(Exception):
    """Base exception for all wallet related errors."""

    status_code = 400
    code = 'wallet_error'
    default_message = _("A wallet error occurred")

    def __init__(self, message=None, **extra):
        self.message = str(message) if message is not None else str(self.default_message)
        self.extra = extra
        super().__init__(self.message)

    @property
    def http_status(self):
        """HTTP status an API should answer with."""
        return type(self).status_code

    def as_dict(self):
        payload = {'detail': self.message, 'code': self.code}
        if self.extra:
            payload.update({k: str(v) if v is not None else None for k, v in self.extra.items()})
        return payload


class InsufficientFunds(WalletError):
    code = 'insufficient_funds'
    default_message = _("Insufficient funds in wallet")

    def __init__(self, wallet=None, amount=None, message=None):
        if message is None and wallet is not None and amount is not None:
            balance = getattr(wallet, 'balance', None)
            message = _("Insufficient funds. Available balance: {balance}, required: {amount}").format(
                balance=balance, amount=amount
            )
        elif message is None and isinstance(wallet, str):
            message = wallet
        super().__init__(message)


class WalletLocked(WalletError):
    status_code = 403
    code = 'wallet_locked'
    default_message = _("Wallet is locked")

    def __init__(self, wallet=None, message=None):
        if message is None and wallet is not None:
            wallet_id = getattr(wallet, 'id', None)
            message = _("Wallet {wallet} is locked").format(wallet=wallet_id) if wallet_id else str(wallet)
        super().__init__(message)


class WalletInactive(WalletLocked):
    code = 'wallet_inactive'
    default_message = _("Wallet is inactive")


class WalletNotFound(WalletError):
    status_code = 404
    code = 'wallet_not_found'
    default_message = _("Wallet not found")


class CurrencyMismatchError(WalletError):
    code = 'currency_mismatch'
    default_message = _("Currency mismatch")


class InvalidAmount(WalletError):
    code = 'invalid_amount'
    default_message = _("Invalid amount")

    def __init__(self, amount=None, message=None):
        if message is None and amount is not None and not isinstance(amount, str):
            message = _("Invalid amount: {amount}").format(amount=amount)
        elif message is None and isinstance(amount, str):
            message = amount
        super().__init__(message)


class TransactionLimitExceeded(WalletError):
    code = 'limit_exceeded'
    default_message = _("Transaction limit exceeded")


# Backwards compatible name
MaximumTransactionLimitExceeded = TransactionLimitExceeded


class MinimumBalanceViolation(WalletError):
    code = 'minimum_balance'
    default_message = _("This transaction would take the wallet below its minimum balance")


class TransactionFailed(WalletError):
    code = 'transaction_failed'
    default_message = _("Transaction failed")

    def __init__(self, reason=None, transaction_id=None):
        message = _("Transaction failed: {reason}").format(reason=reason) if reason else None
        super().__init__(message, transaction_id=transaction_id)


class InvalidTransactionState(WalletError):
    status_code = 409
    code = 'invalid_transaction_state'
    default_message = _("The transaction cannot be changed in its current state")


class DuplicateReference(WalletError):
    status_code = 409
    code = 'duplicate_reference'
    default_message = _("A transaction with this reference already exists")


class FeatureDisabled(WalletError):
    status_code = 403
    code = 'feature_disabled'
    default_message = _("This feature is disabled")


class RecipientNotFound(WalletError):
    status_code = 404
    code = 'recipient_not_found'
    default_message = _("Recipient wallet not found")


class InvalidPhoneNumber(WalletError):
    code = 'invalid_phone_number'
    default_message = _("Invalid phone number")


class PinError(WalletError):
    code = 'pin_error'
    default_message = _("Transaction PIN error")


class PinRequired(PinError):
    code = 'pin_required'
    default_message = _("Transaction PIN is required")


class PinNotSet(PinError):
    code = 'pin_not_set'
    default_message = _("Set a transaction PIN first")


class InvalidPin(PinError):
    status_code = 403
    code = 'invalid_pin'
    default_message = _("Incorrect transaction PIN")


class PinLocked(PinError):
    status_code = 403
    code = 'pin_locked'
    default_message = _("Too many incorrect PIN attempts. Try again later")


class PaystackAPIError(WalletError):
    """
    A Paystack API call failed.

    ``status_code`` is Paystack's HTTP status (None for network errors).
    ``is_definitive`` is True when Paystack rejected the request (4xx) - the
    operation definitely did not happen. For network errors and 5xx responses
    the outcome is unknown and must be reconciled.
    """

    code = 'paystack_error'
    default_message = _("Paystack API error")

    def __init__(self, message=None, status_code=None, response=None):
        text = _("Paystack API error: {message}").format(message=message) if message else None
        super().__init__(text)
        self.paystack_message = str(message) if message else ''
        # Paystack's HTTP status. Our own API answers 502 for gateway errors (see ``http_status``).
        self.status_code = status_code
        self.response = response

    http_status = 502

    @property
    def is_definitive(self):
        return self.status_code is not None and 400 <= self.status_code < 500

    def as_dict(self):
        return {'detail': self.message, 'code': self.code}


class InvalidPaystackResponse(PaystackAPIError):
    """Paystack returned something that is not JSON (e.g. a gateway error page)."""

    code = 'invalid_paystack_response'
    default_message = _("Invalid response from Paystack")

    def __init__(self, response=None, status_code=None):
        super().__init__(message=f"Invalid response: {response}" if response else None, status_code=status_code)
        self.response = response

    @property
    def is_definitive(self):
        # A non-JSON body (proxy/gateway page) tells us nothing about the outcome
        return False


class PaystackConfigurationError(WalletError):
    status_code = 500
    code = 'paystack_not_configured'
    default_message = _("Paystack is not configured. Set PAYSTACK_SECRET_KEY.")


class InvalidWebhookSignature(WalletError):
    status_code = 401
    code = 'invalid_signature'
    default_message = _("Invalid webhook signature")


class CardError(WalletError):
    code = 'card_error'
    default_message = _("Card error")

    def __init__(self, message=None, card_id=None):
        super().__init__(message, card_id=card_id) if card_id else super().__init__(message)


class BankAccountError(WalletError):
    code = 'bank_account_error'
    default_message = _("Bank account error")

    def __init__(self, message=None, account_id=None):
        super().__init__(message, account_id=account_id) if account_id else super().__init__(message)


class RecipientError(WalletError):
    code = 'recipient_error'
    default_message = _("Recipient error")


class SettlementError(WalletError):
    code = 'settlement_error'
    default_message = _("Settlement error")

    def __init__(self, message=None, settlement_id=None):
        super().__init__(message, settlement_id=settlement_id) if settlement_id else super().__init__(message)


class IdempotencyKeyRequired(WalletError):
    code = 'idempotency_key_required'
    default_message = _("An Idempotency-Key header is required for this request")


class IdempotencyKeyMismatch(WalletError):
    status_code = 422
    code = 'idempotency_key_reused'
    default_message = _("This Idempotency-Key was already used with a different request")


class IdempotencyInProgress(WalletError):
    status_code = 409
    code = 'idempotency_in_progress'
    default_message = _(
        "A request with this Idempotency-Key is still being processed (or was interrupted). "
        "Check the transaction status before retrying with a new key"
    )
