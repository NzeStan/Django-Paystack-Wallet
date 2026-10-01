"""Saved cards (reusable Paystack authorizations)."""
import logging

from django.db import IntegrityError, transaction as db_transaction

from wallet.conf import wallet_settings
from wallet.exceptions import CardError, PaystackAPIError
from wallet.models import Card
from wallet.models.card import normalize_card_type
from wallet.services.base import BaseService
from wallet.signals import card_saved, send_on_commit

logger = logging.getLogger('wallet')


class CardService(BaseService):

    def save_card_from_authorization(self, wallet, authorization, customer_email=None):
        """
        Create or refresh a Card from a Paystack ``authorization`` object.

        Only reusable card authorizations are stored. The same physical card
        (same ``signature``) is updated rather than duplicated.
        """
        if not wallet_settings.SAVE_CARDS or not isinstance(authorization, dict):
            return None
        code = authorization.get('authorization_code')
        if not code or not authorization.get('reusable') or (authorization.get('channel') or 'card') != 'card':
            return None

        signature = authorization.get('signature') or ''
        defaults = {
            'card_type': normalize_card_type(authorization.get('card_type') or authorization.get('brand')),
            'last_four': str(authorization.get('last4') or '')[-4:],
            'expiry_month': str(authorization.get('exp_month') or '').zfill(2)[:2],
            'expiry_year': str(authorization.get('exp_year') or '')[:4],
            'bin': str(authorization.get('bin') or '')[:8],
            'bank': (authorization.get('bank') or '')[:100],
            'country_code': (authorization.get('country_code') or '')[:2],
            'card_holder_name': (authorization.get('account_name') or '')[:255],
            'email': customer_email or '',
            'paystack_authorization_code': code,
            'paystack_authorization_signature': signature,
            'paystack_card_data': authorization,
            'is_active': True,
        }

        existing = None
        if signature:
            existing = Card.objects.filter(wallet=wallet, paystack_authorization_signature=signature).first()
        if existing is None:
            existing = Card.objects.filter(wallet=wallet, paystack_authorization_code=code).first()

        try:
            with db_transaction.atomic():
                if existing is not None:
                    for field, value in defaults.items():
                        if field == 'email' and not value:
                            continue
                        setattr(existing, field, value)
                    existing.save()
                    card, created = existing, False
                else:
                    is_first = not Card.objects.filter(wallet=wallet, is_active=True).exists()
                    card = Card.objects.create(wallet=wallet, is_default=is_first, **defaults)
                    created = True
        except IntegrityError:
            logger.warning("Card for authorization %s already saved", code)
            return Card.objects.filter(wallet=wallet, paystack_authorization_code=code).first()

        send_on_commit(card_saved, sender=Card, card=card, wallet=wallet, created=created)
        return card

    def remove_card(self, card, deactivate_on_paystack=True):
        """Soft-delete a card and (optionally) revoke the authorization at Paystack."""
        if deactivate_on_paystack and card.paystack_authorization_code:
            try:
                self.paystack.customers.deactivate_authorization(card.paystack_authorization_code)
            except PaystackAPIError as exc:
                logger.warning("Could not deactivate authorization for card %s: %s", card.pk, exc)
        card.remove()
        return card

    def get_default_card(self, wallet):
        return Card.objects.filter(wallet=wallet, is_active=True).order_by('-is_default', '-created_at').first()

    def check_card(self, card, wallet=None):
        if wallet is not None and card.wallet_id != wallet.pk:
            raise CardError("Card does not belong to this wallet")
        if not card.is_active:
            raise CardError("Card is not active")
        if card.is_expired:
            raise CardError("Card has expired")
        if not card.paystack_authorization_code:
            raise CardError("Card has no Paystack authorization")
        return card
