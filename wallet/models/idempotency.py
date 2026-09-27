from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from wallet.models.base import BaseModel


class IdempotencyRecord(BaseModel):
    """
    Remembers the response to a money-moving API request sent with an
    ``Idempotency-Key`` header, so a client retry (after a timeout, a dropped
    connection, a double tap) replays that response instead of moving money twice.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet_idempotency_records',
        verbose_name=_('User'),
    )
    key = models.CharField(max_length=255, verbose_name=_('Key'))
    endpoint = models.CharField(max_length=255, verbose_name=_('Endpoint'))
    request_hash = models.CharField(max_length=64, verbose_name=_('Request hash'))
    is_complete = models.BooleanField(default=False, verbose_name=_('Complete'))
    response_status = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Response status'))
    response_body = models.JSONField(null=True, blank=True, verbose_name=_('Response body'))

    class Meta:
        verbose_name = _('Idempotency record')
        verbose_name_plural = _('Idempotency records')
        constraints = [
            models.UniqueConstraint(fields=['user', 'key'], name='idempotency_unique_user_key'),
        ]

    def __str__(self):
        return f"{self.key} ({self.endpoint})"
