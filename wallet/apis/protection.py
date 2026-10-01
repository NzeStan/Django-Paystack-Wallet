"""
Request protection for the wallet API: rate limiting and idempotency keys.

Rate limits (``WALLET_THROTTLE_RATES``) are counted per user, or per IP for
anonymous requests, in Django's cache. With several app servers, point
``CACHES['default']`` at Redis or Memcached so limits are shared.

Idempotency: a client sends ``Idempotency-Key: <uuid>`` with a money-moving POST.
The first response is stored; a retry with the same key and body gets that same
response back (header ``Idempotent-Replayed: true``) instead of moving money again.
"""
import hashlib
import json
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone
from rest_framework.throttling import SimpleRateThrottle

from wallet.conf import wallet_settings
from wallet.exceptions import (
    IdempotencyInProgress,
    IdempotencyKeyMismatch,
    IdempotencyKeyRequired,
    InvalidAmount,
)
from wallet.models import IdempotencyRecord


class WalletRateThrottle(SimpleRateThrottle):
    """Throttle whose rate comes from ``WALLET_THROTTLE_RATES[scope]``."""

    def __init__(self, scope):
        self.scope = scope
        super().__init__()

    def get_rate(self):
        if not wallet_settings.ENABLE_THROTTLING:
            return None
        return (wallet_settings.THROTTLE_RATES or {}).get(self.scope)

    def get_cache_key(self, request, view):
        user = getattr(request, 'user', None)
        ident = f"user-{user.pk}" if user is not None and user.is_authenticated else self.get_ident(request)
        return f"wallet-throttle-{self.scope}-{ident}"


class IdempotentReplay(Exception):
    """Raised to short-circuit a request whose response was already stored."""

    def __init__(self, record):
        super().__init__(record.key)
        self.record = record


def _request_hash(request, endpoint):
    try:
        payload = json.dumps(request.data, sort_keys=True, cls=DjangoJSONEncoder, default=str)
    except (TypeError, ValueError):
        payload = str(request.data)
    return hashlib.sha256(f"{endpoint}\n{payload}".encode('utf-8')).hexdigest()


def begin(request):
    """
    Start idempotent handling for ``request``.

    Returns the new in-progress record, or None when no key was sent. Raises
    IdempotentReplay / IdempotencyInProgress / IdempotencyKeyMismatch.
    """
    key = request.headers.get(wallet_settings.IDEMPOTENCY_HEADER)
    if not key:
        if wallet_settings.REQUIRE_IDEMPOTENCY_KEY:
            raise IdempotencyKeyRequired()
        return None
    key = key.strip()
    if not key or len(key) > 255:
        raise InvalidAmount(message="Idempotency-Key must be 1-255 characters")

    endpoint = f"{request.method} {request.path}"[:255]
    request_hash = _request_hash(request, endpoint)
    expired_before = timezone.now() - timedelta(hours=int(wallet_settings.IDEMPOTENCY_TTL_HOURS))
    IdempotencyRecord.objects.filter(user=request.user, key=key, created_at__lt=expired_before).delete()

    try:
        with db_transaction.atomic():
            return IdempotencyRecord.objects.create(
                user=request.user, key=key, endpoint=endpoint, request_hash=request_hash,
            )
    except IntegrityError:
        existing = IdempotencyRecord.objects.filter(user=request.user, key=key).first()
        if existing is None:        # expired and deleted concurrently; treat as in progress
            raise IdempotencyInProgress()
        if existing.request_hash != request_hash:
            raise IdempotencyKeyMismatch()
        if existing.is_complete:
            raise IdempotentReplay(existing)
        raise IdempotencyInProgress()


def finish(record, response):
    """Store the response for replay (or forget the key if the server failed)."""
    if record is None:
        return
    if response.status_code >= 500 or not hasattr(response, 'data'):
        IdempotencyRecord.objects.filter(pk=record.pk).delete()
        return
    record.response_status = response.status_code
    record.response_body = json.loads(json.dumps(response.data, cls=DjangoJSONEncoder))
    record.is_complete = True
    record.save(update_fields=['response_status', 'response_body', 'is_complete', 'updated_at'])
