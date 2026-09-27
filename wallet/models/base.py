import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_('Created at'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated at'))

    class Meta:
        abstract = True


class BaseModel(TimestampedModel):
    """
    Base for every wallet model: UUID primary key + timestamps.

    UUIDs are not guessable (safe to expose in URLs) and the schema is fixed,
    so the shipped migrations always match your database.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name=_('ID'))

    class Meta:
        abstract = True
