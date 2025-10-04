import uuid
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wallet.settings import get_wallet_setting


class UUIDModel(models.Model):
    """Base abstract model with UUID primary key"""
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_('ID')
    )

    class Meta:
        abstract = True


class IDModel(models.Model):
    """Base abstract model with auto-incrementing ID primary key"""
    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    """Base abstract model with created and updated timestamp fields"""
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created at')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Updated at')
    )

    class Meta:
        abstract = True


def get_base_model():
    """Return the appropriate base model class based on settings"""
    base_models = [TimestampedModel]
    if get_wallet_setting('USE_UUID'):
        base_models.append(UUIDModel)
    else:
        base_models.append(IDModel)
    return tuple(base_models)


class BaseModel(*get_base_model()):
    """Base model that includes UUID or ID and timestamps"""
    class Meta:
        abstract = True