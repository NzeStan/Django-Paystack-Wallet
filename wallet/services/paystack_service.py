"""
Backwards-compatible import location. The client now lives in :mod:`wallet.paystack`.
"""
from wallet.paystack import PaystackClient, get_paystack_client, verify_signature  # noqa: F401

PaystackService = PaystackClient
