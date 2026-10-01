"""Reference and tag generators (cryptographically random, collision resistant)."""
import secrets
import string
import time
import uuid

_ALPHABET = string.ascii_uppercase + string.digits


def generate_random_string(length=10, include_digits=True, include_uppercase=True, include_lowercase=False):
    chars = ''
    if include_digits:
        chars += string.digits
    if include_uppercase:
        chars += string.ascii_uppercase
    if include_lowercase:
        chars += string.ascii_lowercase
    chars = chars or _ALPHABET
    return ''.join(secrets.choice(chars) for _ in range(length))


def _reference(prefix):
    # Paystack references allow alphanumerics, '-', '.', '='
    return f"{prefix}-{int(time.time())}-{generate_random_string(10)}"


def generate_transaction_reference(prefix='TRX'):
    return _reference(prefix)


def generate_settlement_reference(prefix='STL'):
    return _reference(prefix)


def generate_charge_reference(prefix='CHG'):
    return _reference(prefix)


def generate_transfer_reference(prefix='TRF'):
    # Paystack requires transfer references to be lowercase alphanumerics, '-' or '_'
    return _reference(prefix).lower()


def generate_refund_reference(prefix='RFD'):
    return _reference(prefix)


def generate_wallet_tag(user=None):
    """
    Generate a human friendly, unique-looking wallet tag from the user's
    username or email. Uniqueness is enforced by the caller.
    """
    base = ''
    if user is not None:
        base = getattr(user, 'username', None) or (getattr(user, 'email', None) or '').split('@')[0]
    base = ''.join(c for c in str(base) if c.isalnum()).lower()[:12]
    if len(base) < 3:
        base = f"w{uuid.uuid4().hex[:6]}"
    return base
