"""Banks, payout bank accounts and Paystack transfer recipients."""
import logging

from django.db import transaction as db_transaction
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from wallet.conf import wallet_settings
from wallet.constants import (
    RECIPIENT_TYPE_BASA,
    RECIPIENT_TYPE_GHIPSS,
    RECIPIENT_TYPE_KEPSS,
    RECIPIENT_TYPE_MOBILE_MONEY,
    RECIPIENT_TYPE_NUBAN,
)
from wallet.exceptions import BankAccountError, PaystackAPIError
from wallet.models import Bank, BankAccount
from wallet.services.base import BaseService
from wallet.signals import bank_account_added, send_on_commit

logger = logging.getLogger('wallet')

# Paystack bank `type` -> transfer recipient type
BANK_TYPE_TO_RECIPIENT = {
    'nuban': RECIPIENT_TYPE_NUBAN,
    'mobile_money': RECIPIENT_TYPE_MOBILE_MONEY,
    'ghipss': RECIPIENT_TYPE_GHIPSS,
    'basa': RECIPIENT_TYPE_BASA,
    'kepss': RECIPIENT_TYPE_KEPSS,
}


class BankAccountService(BaseService):

    # ------------------------------------------------------------------
    # Banks
    # ------------------------------------------------------------------

    def list_banks(self, country=None, currency=None):
        """Banks from the local table (run ``manage.py sync_banks`` to populate)."""
        queryset = Bank.objects.active()
        if currency:
            queryset = queryset.filter(currency__iexact=currency)
        if country:
            queryset = queryset.filter(country__iexact=country)
        return queryset

    def sync_banks(self, country=None, currency=None, force_update=True):
        """Fetch banks from Paystack into the Bank table. Returns (created, updated, errors)."""
        country = country or wallet_settings.BANK_COUNTRY
        created = updated = errors = 0
        for item in self._fetch_all_banks(country, currency):
            try:
                code = str(item.get('code') or '').strip()
                if not code:
                    continue
                bank_currency = (item.get('currency') or currency or wallet_settings.CURRENCY).upper()
                bank_type = item.get('type') or 'nuban'
                values = {
                    'name': item.get('name') or code,
                    'slug': item.get('slug') or slugify(item.get('name') or code),
                    'country': item.get('country') or country,
                    'paystack_id': item.get('id'),
                    'supports_transfer': bool(item.get('supports_transfer', True)),
                    'pay_with_bank': bool(item.get('pay_with_bank', False)),
                    'is_active': bool(item.get('active', True)) and not item.get('is_deleted', False),
                    'paystack_data': item,
                }
                bank, was_created = Bank.objects.get_or_create(
                    code=code, currency=bank_currency, type=bank_type, defaults=values,
                )
                if was_created:
                    created += 1
                elif force_update:
                    for field, value in values.items():
                        setattr(bank, field, value)
                    bank.save()
                    updated += 1
            except Exception:
                errors += 1
                logger.exception("Could not sync bank %s", item.get('code'))
        return created, updated, errors

    def _fetch_all_banks(self, country, currency):
        """Walk Paystack's cursor-paginated bank list."""
        cursor = None
        for _page in range(50):
            body = self.paystack.request('GET', 'bank', params={
                'country': country, 'currency': currency, 'use_cursor': 'true', 'perPage': 100, 'next': cursor,
            }, raw=True)
            yield from body.get('data') or []
            cursor = (body.get('meta') or {}).get('next')
            if not cursor:
                return

    # ------------------------------------------------------------------
    # Account resolution
    # ------------------------------------------------------------------

    def resolve_account(self, account_number, bank_code):
        """Return {'account_number', 'account_name', 'bank_id'} from Paystack."""
        try:
            return self.paystack.verification.resolve_account(account_number=account_number, bank_code=bank_code)
        except PaystackAPIError as exc:
            if exc.is_definitive:
                raise BankAccountError(_("Could not verify account: {error}").format(
                    error=exc.paystack_message or exc.message
                )) from exc
            raise

    verify_bank_account = resolve_account

    # ------------------------------------------------------------------
    # Bank accounts
    # ------------------------------------------------------------------

    def add_bank_account(self, wallet, bank_code, account_number, account_name=None, account_type=None, bvn=None,
                         currency=None, set_default=None, verify=True):
        """
        Verify an account with Paystack, save it and create its transfer recipient.

        The resolved account name from Paystack always wins over a supplied name
        (prevents payouts to mislabelled accounts).
        """
        currency = (currency or wallet.currency).upper()
        bank = Bank.objects.filter(code=bank_code, currency=currency, is_active=True).first() \
            or Bank.objects.filter(code=bank_code, is_active=True).first()
        if bank is None:
            raise BankAccountError(_("Bank with code {code} not found. Run 'manage.py sync_banks'.").format(
                code=bank_code
            ))

        is_verified = False
        recipient_type = BANK_TYPE_TO_RECIPIENT.get(bank.type or 'nuban', RECIPIENT_TYPE_NUBAN)
        if verify and recipient_type == RECIPIENT_TYPE_NUBAN:
            resolved = self.resolve_account(account_number, bank.code)
            account_name = resolved.get('account_name') or account_name
            is_verified = True
        if not account_name:
            raise BankAccountError(_("Account name is required"))

        with db_transaction.atomic():
            bank_account = BankAccount.objects.filter(wallet=wallet, bank=bank, account_number=account_number).first()
            if bank_account is not None:
                bank_account.account_name = account_name
                bank_account.is_active = True
                bank_account.is_verified = bank_account.is_verified or is_verified
                if bvn:
                    bank_account.bvn = bvn
                if account_type:
                    bank_account.account_type = account_type
                bank_account.save()
            else:
                fields = {
                    'wallet': wallet, 'bank': bank, 'account_number': account_number, 'account_name': account_name,
                    'is_verified': is_verified, 'bvn': bvn or '', 'currency': currency,
                    'recipient_type': recipient_type,
                }
                if account_type:
                    fields['account_type'] = account_type
                bank_account = BankAccount.objects.create(**fields)

            has_default = BankAccount.objects.filter(wallet=wallet, is_default=True, is_active=True).exclude(
                pk=bank_account.pk
            ).exists()
            if set_default or (set_default is None and not has_default):
                bank_account.set_as_default()

        try:
            self.ensure_recipient(bank_account)
        except (PaystackAPIError, BankAccountError) as exc:
            # Not fatal: the recipient is created again on the first withdrawal.
            logger.warning("Could not create transfer recipient for bank account %s: %s", bank_account.pk, exc)

        send_on_commit(bank_account_added, sender=BankAccount, bank_account=bank_account, wallet=wallet)
        return bank_account

    def ensure_recipient(self, bank_account):
        """Make sure the account has a Paystack transfer recipient code."""
        if bank_account.paystack_recipient_code:
            return bank_account.paystack_recipient_code
        try:
            data = self.paystack.transfer_recipients.create(
                type=bank_account.recipient_type or RECIPIENT_TYPE_NUBAN,
                name=bank_account.account_name,
                account_number=bank_account.account_number,
                bank_code=bank_account.bank.code,
                currency=bank_account.currency,
                metadata={'wallet_id': str(bank_account.wallet_id), 'bank_account_id': str(bank_account.pk)},
            )
        except PaystackAPIError as exc:
            if exc.is_definitive:
                raise BankAccountError(_("Paystack rejected the account: {error}").format(
                    error=exc.paystack_message or exc.message
                )) from exc
            raise
        bank_account.paystack_recipient_code = data.get('recipient_code')
        bank_account.paystack_recipient_id = data.get('id')
        bank_account.paystack_data = data
        details = data.get('details') or {}
        if details.get('account_name') and not bank_account.is_verified:
            bank_account.account_name = details['account_name']
        bank_account.save(update_fields=[
            'paystack_recipient_code', 'paystack_recipient_id', 'paystack_data', 'account_name', 'updated_at',
        ])
        return bank_account.paystack_recipient_code

    def remove_bank_account(self, bank_account, delete_recipient=False):
        if delete_recipient and bank_account.paystack_recipient_code:
            try:
                self.paystack.transfer_recipients.delete(bank_account.paystack_recipient_code)
            except PaystackAPIError as exc:
                logger.warning("Could not delete recipient %s: %s", bank_account.paystack_recipient_code, exc)
        bank_account.remove()
        return bank_account

    def get_default_bank_account(self, wallet):
        return BankAccount.objects.filter(wallet=wallet, is_active=True).order_by('-is_default', '-created_at').first()
