from django.utils.translation import gettext_lazy as _


class WalletError(Exception):
    """Base exception for all wallet related errors"""
    pass


class InsufficientFunds(WalletError):
    """Exception raised when a wallet has insufficient funds for a transaction"""
    def __init__(self, wallet=None, amount=None):
        message = _("Insufficient funds in wallet")
        if wallet and amount:
            message = _("Insufficient funds in wallet: {wallet}. Available balance: {balance}, Required amount: {amount}").format(
                wallet=wallet.id,
                balance=wallet.balance,
                amount=amount
            )
        super().__init__(message)


class WalletLocked(WalletError):
    """Exception raised when a wallet is locked"""
    def __init__(self, wallet=None):
        # Default message
        message = _("Wallet is locked")

        if wallet:
            try:
                # If it's a Wallet instance with .id
                wallet_id = wallet.id
                message = _("Wallet {wallet} is locked").format(wallet=wallet_id)
            except AttributeError:
                # If wallet is a string or anything else
                message = str(wallet)

        super().__init__(message)

class CurrencyMismatchError(Exception):
    """Raised when currencies don't match"""
    pass

class InvalidAmount(WalletError):
    """Exception raised when an invalid amount is provided"""
    def __init__(self, amount=None):
        message = _("Invalid amount")
        if amount is not None:
            message = _("Invalid amount: {amount}").format(amount=amount)
        super().__init__(message)


class MaximumTransactionLimitExceeded(WalletError):
    """Exception raised when a transaction exceeds the maximum limit"""
    def __init__(self, limit=None):
        message = _("Maximum transaction limit exceeded")
        if limit:
            message = _("Maximum transaction limit of {limit} exceeded").format(limit=limit)
        super().__init__(message)


class TransactionFailed(WalletError):
    """Exception raised when a transaction fails"""
    def __init__(self, reason=None, transaction_id=None):
        message = _("Transaction failed")
        if reason:
            message = _("Transaction failed: {reason}").format(reason=reason)
        if transaction_id:
            message = _("{message} (Transaction ID: {transaction_id})").format(
                message=message,
                transaction_id=transaction_id
            )
        super().__init__(message)


class InvalidPaystackResponse(WalletError):
    """Exception raised when an invalid response is received from Paystack"""
    def __init__(self, response=None):
        message = _("Invalid response from Paystack")
        if response:
            message = _("Invalid response from Paystack: {response}").format(response=response)
        super().__init__(message)
        self.response = response


class PaystackAPIError(WalletError):
    """Exception raised when a Paystack API call fails"""
    def __init__(self, message=None, status_code=None, response=None):
        msg = _("Paystack API error")
        if message:
            msg = _("Paystack API error: {message}").format(message=message)
        if status_code:
            msg = _("{msg} (Status code: {status_code})").format(msg=msg, status_code=status_code)
        super().__init__(msg)
        self.response = response
        self.status_code = status_code


class InvalidWebhookSignature(WalletError):
    """Exception raised when a webhook signature is invalid"""
    def __init__(self):
        message = _("Invalid webhook signature")
        super().__init__(message)


class CardError(WalletError):
    """Exception raised when there is an error with a card"""
    def __init__(self, message=None, card_id=None):
        msg = _("Card error")
        if message:
            msg = _("Card error: {message}").format(message=message)
        if card_id:
            msg = _("{msg} (Card ID: {card_id})").format(msg=msg, card_id=card_id)
        super().__init__(msg)


class BankAccountError(WalletError):
    """Exception raised when there is an error with a bank account"""
    def __init__(self, message=None, account_id=None):
        msg = _("Bank account error")
        if message:
            msg = _("Bank account error: {message}").format(message=message)
        if account_id:
            msg = _("{msg} (Account ID: {account_id})").format(msg=msg, account_id=account_id)
        super().__init__(msg)


class RecipientError(WalletError):
    """Exception raised when there is an error with a transfer recipient"""
    def __init__(self, message=None, recipient_id=None):
        msg = _("Recipient error")
        if message:
            msg = _("Recipient error: {message}").format(message=message)
        if recipient_id:
            msg = _("{msg} (Recipient ID: {recipient_id})").format(msg=msg, recipient_id=recipient_id)
        super().__init__(msg)


class SettlementError(WalletError):
    """Exception raised when there is an error with a settlement"""
    def __init__(self, message=None, settlement_id=None):
        msg = _("Settlement error")
        if message:
            msg = _("Settlement error: {message}").format(message=message)
        if settlement_id:
            msg = _("{msg} (Settlement ID: {settlement_id})").format(msg=msg, settlement_id=settlement_id)
        super().__init__(msg)