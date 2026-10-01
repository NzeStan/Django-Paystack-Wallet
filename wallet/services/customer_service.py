"""Paystack customers, identity validation and dedicated virtual accounts (DVA)."""
import logging

from django.utils.translation import gettext_lazy as _

from wallet.conf import wallet_settings
from wallet.exceptions import PaystackAPIError, WalletError
from wallet.models import Wallet
from wallet.services.base import BaseService
from wallet.signals import (
    customer_identification,
    dedicated_account_assigned,
    dedicated_account_failed,
    send_on_commit,
)

logger = logging.getLogger('wallet')


def _user_names(user):
    first = getattr(user, 'first_name', '') or ''
    last = getattr(user, 'last_name', '') or ''
    return first, last


class CustomerService(BaseService):

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def ensure_customer(self, wallet):
        """Create (or link) the Paystack customer for a wallet and return its code."""
        if wallet.paystack_customer_code:
            return wallet.paystack_customer_code
        user = wallet.user
        email = getattr(user, 'email', None)
        if not email:
            raise WalletError(_("The user needs an email address to create a Paystack customer"))
        first, last = _user_names(user)
        data = self.paystack.customers.create(
            email=email, first_name=first or None, last_name=last or None, phone=wallet.phone_number or None,
            metadata={'wallet_id': str(wallet.pk), 'user_id': str(user.pk)},
        )
        self._store_customer(wallet, data)
        return wallet.paystack_customer_code

    setup_paystack_customer = ensure_customer

    def _store_customer(self, wallet, data):
        code = (data or {}).get('customer_code')
        if not code:
            return
        wallet.paystack_customer_code = code
        wallet.paystack_customer_id = data.get('id')
        wallet.customer_identified = bool(data.get('identified', wallet.customer_identified))
        wallet.save(update_fields=[
            'paystack_customer_code', 'paystack_customer_id', 'customer_identified', 'updated_at',
        ])

    def update_customer(self, wallet, **fields):
        """Update first_name, last_name, phone or metadata on Paystack."""
        code = self.ensure_customer(wallet)
        return self.paystack.customers.update(code, **fields)

    def fetch_customer(self, wallet):
        return self.paystack.customers.fetch(self.ensure_customer(wallet))

    def validate_customer(self, wallet, first_name, last_name, identification_type='bank_account', country='NG',
                          bvn=None, bank_code=None, account_number=None, value=None, middle_name=None):
        """
        Start Paystack identity validation (needed before a DVA can be issued
        for most Nigerian businesses). The result arrives via the
        ``customeridentification.*`` webhook.
        """
        code = self.ensure_customer(wallet)
        return self.paystack.customers.validate(
            code, first_name=first_name, last_name=last_name, type=identification_type, country=country,
            bvn=bvn, bank_code=bank_code, account_number=account_number, value=value, middle_name=middle_name,
        )

    def set_risk_action(self, wallet, risk_action):
        """Whitelist ('allow'), blacklist ('deny') or reset ('default') a customer on Paystack."""
        return self.paystack.customers.set_risk_action(self.ensure_customer(wallet), risk_action)

    # ------------------------------------------------------------------
    # Dedicated virtual accounts
    # ------------------------------------------------------------------

    def create_dedicated_account(self, wallet, preferred_bank=None, subaccount=None, split_code=None):
        """Create a DVA for the wallet's customer and store it. Returns the wallet."""
        self.require_feature('DEDICATED_ACCOUNTS')
        if wallet.dedicated_account_number and wallet.dedicated_account_active:
            return wallet
        code = self.ensure_customer(wallet)
        first, last = _user_names(wallet.user)
        data = self.paystack.dedicated_accounts.create(
            customer=code,
            preferred_bank=preferred_bank or wallet_settings.DEDICATED_ACCOUNT_PROVIDER,
            subaccount=subaccount, split_code=split_code,
            first_name=first or None, last_name=last or None, phone=wallet.phone_number or None,
        )
        self.store_dedicated_account(wallet, data)
        return wallet

    def assign_dedicated_account(self, wallet, first_name=None, last_name=None, phone=None, preferred_bank=None,
                                 country='NG', bvn=None, account_number=None, bank_code=None, subaccount=None,
                                 split_code=None, middle_name=None):
        """
        One-step: create customer, validate identity and assign an account.
        Completion is reported by the ``dedicatedaccount.assign.*`` webhooks.
        """
        self.require_feature('DEDICATED_ACCOUNTS')
        user = wallet.user
        user_first, user_last = _user_names(user)
        return self.paystack.dedicated_accounts.assign(
            email=user.email, first_name=first_name or user_first, last_name=last_name or user_last,
            middle_name=middle_name, phone=phone or wallet.phone_number,
            preferred_bank=preferred_bank or wallet_settings.DEDICATED_ACCOUNT_PROVIDER, country=country,
            bvn=bvn, account_number=account_number, bank_code=bank_code, subaccount=subaccount,
            split_code=split_code,
        )

    def store_dedicated_account(self, wallet, data):
        data = data or {}
        if not data.get('account_number'):
            return wallet
        bank = data.get('bank') or {}
        wallet.dedicated_account_id = data.get('id') or wallet.dedicated_account_id
        wallet.dedicated_account_number = data.get('account_number')
        wallet.dedicated_account_name = data.get('account_name')
        wallet.dedicated_account_bank = bank.get('name')
        wallet.dedicated_account_bank_slug = bank.get('slug')
        wallet.dedicated_account_active = bool(data.get('active', True))
        customer = data.get('customer') or {}
        if customer.get('customer_code') and not wallet.paystack_customer_code:
            wallet.paystack_customer_code = customer['customer_code']
            wallet.paystack_customer_id = customer.get('id')
        wallet.save()
        return wallet

    def get_dedicated_account(self, wallet, refresh=False):
        if refresh and wallet.dedicated_account_id:
            self.store_dedicated_account(wallet, self.paystack.dedicated_accounts.fetch(wallet.dedicated_account_id))
        return {
            'account_number': wallet.dedicated_account_number,
            'account_name': wallet.dedicated_account_name,
            'bank_name': wallet.dedicated_account_bank,
            'bank_slug': wallet.dedicated_account_bank_slug,
            'active': wallet.dedicated_account_active,
        }

    def requery_dedicated_account(self, wallet, date=None):
        """Ask Paystack to check for transfers into the DVA that were not yet notified."""
        if not wallet.dedicated_account_number:
            raise WalletError(_("This wallet has no dedicated account"))
        return self.paystack.dedicated_accounts.requery(
            account_number=wallet.dedicated_account_number,
            provider_slug=wallet.dedicated_account_bank_slug or wallet_settings.DEDICATED_ACCOUNT_PROVIDER,
            date=date,
        )

    def deactivate_dedicated_account(self, wallet):
        if not wallet.dedicated_account_id:
            raise WalletError(_("This wallet has no dedicated account"))
        data = self.paystack.dedicated_accounts.deactivate(wallet.dedicated_account_id)
        wallet.dedicated_account_active = False
        wallet.save(update_fields=['dedicated_account_active', 'updated_at'])
        return data

    def dedicated_account_providers(self):
        return self.paystack.dedicated_accounts.providers()

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    @staticmethod
    def _wallet_for_customer(customer):
        customer = customer or {}
        code = customer.get('customer_code')
        if code:
            wallet = Wallet.objects.filter(paystack_customer_code=code).first()
            if wallet:
                return wallet
        email = customer.get('email')
        if email:
            return Wallet.objects.filter(user__email__iexact=email).first()
        return None

    def process_dedicated_account_event(self, event, data):
        wallet = self._wallet_for_customer(data.get('customer'))
        if wallet is None:
            logger.info("DVA event %s for unknown customer", event)
            return None
        if event.endswith('success'):
            customer = data.get('customer') or {}
            if customer.get('customer_code') and not wallet.paystack_customer_code:
                self._store_customer(wallet, customer)
            self.store_dedicated_account(wallet, data.get('dedicated_account') or {})
            send_on_commit(dedicated_account_assigned, sender=Wallet, wallet=wallet, data=data)
        else:
            send_on_commit(dedicated_account_failed, sender=Wallet, wallet=wallet, data=data)
        return wallet

    def process_identification_event(self, event, data):
        wallet = None
        code = data.get('customer_code')
        if code:
            wallet = Wallet.objects.filter(paystack_customer_code=code).first()
        if wallet is None and data.get('email'):
            wallet = Wallet.objects.filter(user__email__iexact=data['email']).first()
        if wallet is None:
            return None
        success = event.endswith('success')
        wallet.customer_identified = success
        wallet.save(update_fields=['customer_identified', 'updated_at'])
        send_on_commit(customer_identification, sender=Wallet, wallet=wallet, success=success, data=data)

        if success and wallet_settings.AUTO_CREATE_DEDICATED_ACCOUNT and not wallet.dedicated_account_number:
            try:
                self.create_dedicated_account(wallet)
            except (PaystackAPIError, WalletError) as exc:
                logger.warning("DVA creation after identification failed for wallet %s: %s", wallet.pk, exc)
        return wallet
