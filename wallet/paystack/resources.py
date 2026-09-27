"""
Paystack API resources.

Each class maps one section of https://paystack.com/docs/api/ to methods.
Amounts are always in the currency's minor unit (kobo, pesewas, cents), as
Paystack expects. Optional arguments left as ``None`` are not sent. Any extra
keyword arguments are passed through unchanged, so newly added Paystack
parameters work without a package update.
"""
from urllib.parse import quote


def _p(value):
    """URL-encode a path segment."""
    return quote(str(value), safe='')


class Resource:
    def __init__(self, client):
        self.client = client

    def _get(self, path, **params):
        return self.client.request('GET', path, params=params)

    def _post(self, path, data=None):
        return self.client.request('POST', path, json=data or {})

    def _put(self, path, data=None):
        return self.client.request('PUT', path, json=data or {})

    def _delete(self, path, data=None):
        return self.client.request('DELETE', path, json=data)


class Transactions(Resource):
    """https://paystack.com/docs/api/transaction/"""

    def initialize(self, email, amount, currency=None, reference=None, callback_url=None, plan=None,
                   invoice_limit=None, metadata=None, channels=None, split_code=None, subaccount=None,
                   transaction_charge=None, bearer=None, **extra):
        return self._post('transaction/initialize', {
            'email': email, 'amount': amount, 'currency': currency, 'reference': reference,
            'callback_url': callback_url, 'plan': plan, 'invoice_limit': invoice_limit, 'metadata': metadata,
            'channels': channels, 'split_code': split_code, 'subaccount': subaccount,
            'transaction_charge': transaction_charge, 'bearer': bearer, **extra,
        })

    def verify(self, reference):
        return self._get(f'transaction/verify/{_p(reference)}')

    def list(self, **params):
        """Filters: perPage, page, customer, terminalid, status, from, to, amount."""
        return self._get('transaction', **params)

    def fetch(self, transaction_id):
        return self._get(f'transaction/{_p(transaction_id)}')

    def charge_authorization(self, email, amount, authorization_code, reference=None, currency=None,
                             metadata=None, channels=None, subaccount=None, transaction_charge=None,
                             bearer=None, queue=None, **extra):
        return self._post('transaction/charge_authorization', {
            'email': email, 'amount': amount, 'authorization_code': authorization_code, 'reference': reference,
            'currency': currency, 'metadata': metadata, 'channels': channels, 'subaccount': subaccount,
            'transaction_charge': transaction_charge, 'bearer': bearer, 'queue': queue, **extra,
        })

    def timeline(self, id_or_reference):
        return self._get(f'transaction/timeline/{_p(id_or_reference)}')

    def totals(self, **params):
        return self._get('transaction/totals', **params)

    def export(self, **params):
        return self._get('transaction/export', **params)

    def partial_debit(self, authorization_code, currency, amount, email, reference=None, at_least=None, **extra):
        return self._post('transaction/partial_debit', {
            'authorization_code': authorization_code, 'currency': currency, 'amount': amount, 'email': email,
            'reference': reference, 'at_least': at_least, **extra,
        })


class TransactionSplits(Resource):
    """https://paystack.com/docs/api/split/"""

    def create(self, name, type, currency, subaccounts, bearer_type, bearer_subaccount=None, **extra):
        return self._post('split', {
            'name': name, 'type': type, 'currency': currency, 'subaccounts': subaccounts,
            'bearer_type': bearer_type, 'bearer_subaccount': bearer_subaccount, **extra,
        })

    def list(self, **params):
        return self._get('split', **params)

    def fetch(self, split_id):
        return self._get(f'split/{_p(split_id)}')

    def update(self, split_id, **data):
        return self._put(f'split/{_p(split_id)}', data)

    def add_subaccount(self, split_id, subaccount, share):
        return self._post(f'split/{_p(split_id)}/subaccount/add', {'subaccount': subaccount, 'share': share})

    def remove_subaccount(self, split_id, subaccount):
        return self._post(f'split/{_p(split_id)}/subaccount/remove', {'subaccount': subaccount})


class Terminals(Resource):
    """https://paystack.com/docs/api/terminal/"""

    def send_event(self, terminal_id, type, action, data):
        return self._post(f'terminal/{_p(terminal_id)}/event', {'type': type, 'action': action, 'data': data})

    def fetch_event_status(self, terminal_id, event_id):
        return self._get(f'terminal/{_p(terminal_id)}/event/{_p(event_id)}')

    def fetch_status(self, terminal_id):
        return self._get(f'terminal/{_p(terminal_id)}/presence')

    def list(self, **params):
        return self._get('terminal', **params)

    def fetch(self, terminal_id):
        return self._get(f'terminal/{_p(terminal_id)}')

    def update(self, terminal_id, **data):
        return self._put(f'terminal/{_p(terminal_id)}', data)

    def commission(self, serial_number):
        return self._post('terminal/commission_device', {'serial_number': serial_number})

    def decommission(self, serial_number):
        return self._post('terminal/decommission_device', {'serial_number': serial_number})


class VirtualTerminals(Resource):
    """https://paystack.com/docs/api/virtual-terminal/"""

    def create(self, name, destinations, **extra):
        return self._post('virtual_terminal', {'name': name, 'destinations': destinations, **extra})

    def list(self, **params):
        return self._get('virtual_terminal', **params)

    def fetch(self, code):
        return self._get(f'virtual_terminal/{_p(code)}')

    def update(self, code, name):
        return self._put(f'virtual_terminal/{_p(code)}', {'name': name})

    def deactivate(self, code):
        return self._put(f'virtual_terminal/{_p(code)}/deactivate')

    def assign_destination(self, code, destinations):
        return self._post(f'virtual_terminal/{_p(code)}/destination/assign', {'destinations': destinations})

    def unassign_destination(self, code, targets):
        return self._post(f'virtual_terminal/{_p(code)}/destination/unassign', {'targets': targets})

    def add_split_code(self, code, split_code):
        return self._put(f'virtual_terminal/{_p(code)}/split_code', {'split_code': split_code})

    def remove_split_code(self, code, split_code):
        return self._delete(f'virtual_terminal/{_p(code)}/split_code', {'split_code': split_code})


class Customers(Resource):
    """https://paystack.com/docs/api/customer/"""

    def create(self, email, first_name=None, last_name=None, phone=None, metadata=None, **extra):
        return self._post('customer', {
            'email': email, 'first_name': first_name, 'last_name': last_name, 'phone': phone,
            'metadata': metadata, **extra,
        })

    def list(self, **params):
        return self._get('customer', **params)

    def fetch(self, email_or_code):
        return self._get(f'customer/{_p(email_or_code)}')

    def update(self, code, **data):
        return self._put(f'customer/{_p(code)}', data)

    def validate(self, code, first_name, last_name, type, value=None, country='NG', bvn=None, bank_code=None,
                 account_number=None, middle_name=None, **extra):
        """Identity validation (required before assigning a DVA for most Nigerian integrations)."""
        return self._post(f'customer/{_p(code)}/identification', {
            'first_name': first_name, 'last_name': last_name, 'type': type, 'value': value, 'country': country,
            'bvn': bvn, 'bank_code': bank_code, 'account_number': account_number, 'middle_name': middle_name,
            **extra,
        })

    def set_risk_action(self, customer, risk_action='default'):
        """risk_action: 'allow' (whitelist), 'deny' (blacklist) or 'default'."""
        return self._post('customer/set_risk_action', {'customer': customer, 'risk_action': risk_action})

    def deactivate_authorization(self, authorization_code):
        return self._post('customer/deactivate_authorization', {'authorization_code': authorization_code})


class DirectDebit(Resource):
    """https://paystack.com/docs/api/direct-debit/ and customer direct debit endpoints."""

    def initialize_authorization(self, email, channel='direct_debit', callback_url=None, account=None,
                                 address=None, **extra):
        return self._post('customer/authorization/initialize', {
            'email': email, 'channel': channel, 'callback_url': callback_url, 'account': account,
            'address': address, **extra,
        })

    def verify_authorization(self, reference):
        return self._get(f'customer/authorization/verify/{_p(reference)}')

    def initialize(self, customer_id, account, address):
        return self._post(f'customer/{_p(customer_id)}/initialize-direct-debit', {
            'account': account, 'address': address,
        })

    def activation_charge(self, customer_id, authorization_id):
        return self._put(f'customer/{_p(customer_id)}/directdebit-activation-charge', {
            'authorization_id': authorization_id,
        })

    def mandate_authorizations(self, customer_id):
        return self._get(f'customer/{_p(customer_id)}/directdebit-mandate-authorizations')

    def trigger_activation_charge(self, customer_ids):
        return self._put('directdebit/activation-charge', {'customer_ids': customer_ids})

    def list_mandates(self, **params):
        return self._get('directdebit/mandate-authorizations', **params)


class DedicatedAccounts(Resource):
    """https://paystack.com/docs/api/dedicated-virtual-account/"""

    def create(self, customer, preferred_bank=None, subaccount=None, split_code=None, first_name=None,
               last_name=None, phone=None, **extra):
        return self._post('dedicated_account', {
            'customer': customer, 'preferred_bank': preferred_bank, 'subaccount': subaccount,
            'split_code': split_code, 'first_name': first_name, 'last_name': last_name, 'phone': phone, **extra,
        })

    def assign(self, email, first_name, last_name, phone, preferred_bank, country='NG', account_number=None,
               bvn=None, bank_code=None, subaccount=None, split_code=None, middle_name=None, **extra):
        """Create the customer, validate them and assign an account in one step (async - watch webhooks)."""
        return self._post('dedicated_account/assign', {
            'email': email, 'first_name': first_name, 'middle_name': middle_name, 'last_name': last_name,
            'phone': phone, 'preferred_bank': preferred_bank, 'country': country,
            'account_number': account_number, 'bvn': bvn, 'bank_code': bank_code, 'subaccount': subaccount,
            'split_code': split_code, **extra,
        })

    def list(self, **params):
        """Filters: active, currency, provider_slug, bank_id, customer."""
        return self._get('dedicated_account', **params)

    def fetch(self, dedicated_account_id):
        return self._get(f'dedicated_account/{_p(dedicated_account_id)}')

    def requery(self, account_number, provider_slug, date=None):
        return self._get('dedicated_account/requery', account_number=account_number,
                         provider_slug=provider_slug, date=date)

    def deactivate(self, dedicated_account_id):
        return self._delete(f'dedicated_account/{_p(dedicated_account_id)}')

    def split(self, customer, subaccount=None, split_code=None, preferred_bank=None):
        return self._post('dedicated_account/split', {
            'customer': customer, 'subaccount': subaccount, 'split_code': split_code,
            'preferred_bank': preferred_bank,
        })

    def remove_split(self, account_number):
        return self._delete('dedicated_account/split', {'account_number': account_number})

    def providers(self):
        return self._get('dedicated_account/available_providers')


class ApplePay(Resource):
    """https://paystack.com/docs/api/apple-pay/"""

    def register_domain(self, domain_name):
        return self._post('apple-pay/domain', {'domainName': domain_name})

    def list_domains(self, **params):
        return self._get('apple-pay/domain', **params)

    def unregister_domain(self, domain_name):
        return self._delete('apple-pay/domain', {'domainName': domain_name})


class Subaccounts(Resource):
    """https://paystack.com/docs/api/subaccount/"""

    def create(self, business_name, settlement_bank, account_number, percentage_charge, description=None,
               primary_contact_email=None, primary_contact_name=None, primary_contact_phone=None,
               metadata=None, **extra):
        return self._post('subaccount', {
            'business_name': business_name, 'settlement_bank': settlement_bank, 'account_number': account_number,
            'percentage_charge': percentage_charge, 'description': description,
            'primary_contact_email': primary_contact_email, 'primary_contact_name': primary_contact_name,
            'primary_contact_phone': primary_contact_phone, 'metadata': metadata, **extra,
        })

    def list(self, **params):
        return self._get('subaccount', **params)

    def fetch(self, id_or_code):
        return self._get(f'subaccount/{_p(id_or_code)}')

    def update(self, id_or_code, **data):
        return self._put(f'subaccount/{_p(id_or_code)}', data)


class Plans(Resource):
    """https://paystack.com/docs/api/plan/"""

    def create(self, name, amount, interval, description=None, send_invoices=None, send_sms=None,
               currency=None, invoice_limit=None, **extra):
        return self._post('plan', {
            'name': name, 'amount': amount, 'interval': interval, 'description': description,
            'send_invoices': send_invoices, 'send_sms': send_sms, 'currency': currency,
            'invoice_limit': invoice_limit, **extra,
        })

    def list(self, **params):
        return self._get('plan', **params)

    def fetch(self, id_or_code):
        return self._get(f'plan/{_p(id_or_code)}')

    def update(self, id_or_code, **data):
        return self._put(f'plan/{_p(id_or_code)}', data)


class Subscriptions(Resource):
    """https://paystack.com/docs/api/subscription/"""

    def create(self, customer, plan, authorization=None, start_date=None, **extra):
        return self._post('subscription', {
            'customer': customer, 'plan': plan, 'authorization': authorization, 'start_date': start_date, **extra,
        })

    def list(self, **params):
        return self._get('subscription', **params)

    def fetch(self, id_or_code):
        return self._get(f'subscription/{_p(id_or_code)}')

    def enable(self, code, token):
        return self._post('subscription/enable', {'code': code, 'token': token})

    def disable(self, code, token):
        return self._post('subscription/disable', {'code': code, 'token': token})

    def generate_update_link(self, code):
        return self._get(f'subscription/{_p(code)}/manage/link')

    def send_update_link(self, code):
        return self._post(f'subscription/{_p(code)}/manage/email')


class Products(Resource):
    """https://paystack.com/docs/api/product/"""

    def create(self, name, description, price, currency, unlimited=None, quantity=None, **extra):
        return self._post('product', {
            'name': name, 'description': description, 'price': price, 'currency': currency,
            'unlimited': unlimited, 'quantity': quantity, **extra,
        })

    def list(self, **params):
        return self._get('product', **params)

    def fetch(self, product_id):
        return self._get(f'product/{_p(product_id)}')

    def update(self, product_id, **data):
        return self._put(f'product/{_p(product_id)}', data)


class PaymentPages(Resource):
    """https://paystack.com/docs/api/page/"""

    def create(self, name, description=None, amount=None, currency=None, slug=None, type=None, plan=None,
               fixed_amount=None, split_code=None, metadata=None, redirect_url=None,
               success_message=None, notification_email=None, collect_phone=None, custom_fields=None, **extra):
        return self._post('page', {
            'name': name, 'description': description, 'amount': amount, 'currency': currency, 'slug': slug,
            'type': type, 'plan': plan, 'fixed_amount': fixed_amount, 'split_code': split_code,
            'metadata': metadata, 'redirect_url': redirect_url, 'success_message': success_message,
            'notification_email': notification_email, 'collect_phone': collect_phone,
            'custom_fields': custom_fields, **extra,
        })

    def list(self, **params):
        return self._get('page', **params)

    def fetch(self, id_or_slug):
        return self._get(f'page/{_p(id_or_slug)}')

    def update(self, id_or_slug, **data):
        return self._put(f'page/{_p(id_or_slug)}', data)

    def check_slug(self, slug):
        return self._get(f'page/check_slug_availability/{_p(slug)}')

    def add_products(self, page_id, product):
        return self._post(f'page/{_p(page_id)}/product', {'product': product})


class PaymentRequests(Resource):
    """https://paystack.com/docs/api/payment-request/ (invoices)"""

    def create(self, customer, amount=None, due_date=None, description=None, line_items=None, tax=None,
               currency=None, send_notification=None, draft=None, has_invoice=None, invoice_number=None,
               split_code=None, **extra):
        return self._post('paymentrequest', {
            'customer': customer, 'amount': amount, 'due_date': due_date, 'description': description,
            'line_items': line_items, 'tax': tax, 'currency': currency, 'send_notification': send_notification,
            'draft': draft, 'has_invoice': has_invoice, 'invoice_number': invoice_number,
            'split_code': split_code, **extra,
        })

    def list(self, **params):
        return self._get('paymentrequest', **params)

    def fetch(self, id_or_code):
        return self._get(f'paymentrequest/{_p(id_or_code)}')

    def verify(self, code):
        return self._get(f'paymentrequest/verify/{_p(code)}')

    def notify(self, code):
        return self._post(f'paymentrequest/notify/{_p(code)}')

    def totals(self):
        return self._get('paymentrequest/totals')

    def finalize(self, code, send_notification=None):
        return self._post(f'paymentrequest/finalize/{_p(code)}', {'send_notification': send_notification})

    def update(self, id_or_code, **data):
        return self._put(f'paymentrequest/{_p(id_or_code)}', data)

    def archive(self, code):
        return self._post(f'paymentrequest/archive/{_p(code)}')


class Settlements(Resource):
    """https://paystack.com/docs/api/settlement/ (Paystack -> your bank payouts)"""

    def list(self, **params):
        return self._get('settlement', **params)

    def transactions(self, settlement_id, **params):
        return self._get(f'settlement/{_p(settlement_id)}/transactions', **params)


class TransferRecipients(Resource):
    """https://paystack.com/docs/api/transfer-recipient/"""

    def create(self, type, name, account_number=None, bank_code=None, description=None, currency=None,
               authorization_code=None, metadata=None, **extra):
        return self._post('transferrecipient', {
            'type': type, 'name': name, 'account_number': account_number, 'bank_code': bank_code,
            'description': description, 'currency': currency, 'authorization_code': authorization_code,
            'metadata': metadata, **extra,
        })

    def bulk_create(self, batch):
        return self._post('transferrecipient/bulk', {'batch': batch})

    def list(self, **params):
        return self._get('transferrecipient', **params)

    def fetch(self, id_or_code):
        return self._get(f'transferrecipient/{_p(id_or_code)}')

    def update(self, id_or_code, name=None, email=None):
        return self._put(f'transferrecipient/{_p(id_or_code)}', {'name': name, 'email': email})

    def delete(self, id_or_code):
        return self._delete(f'transferrecipient/{_p(id_or_code)}')


class Transfers(Resource):
    """https://paystack.com/docs/api/transfer/"""

    def initiate(self, amount, recipient, reference=None, reason=None, currency=None, source='balance',
                 account_reference=None, **extra):
        return self._post('transfer', {
            'source': source, 'amount': amount, 'recipient': recipient, 'reference': reference,
            'reason': reason, 'currency': currency, 'account_reference': account_reference, **extra,
        })

    def finalize(self, transfer_code, otp):
        return self._post('transfer/finalize_transfer', {'transfer_code': transfer_code, 'otp': otp})

    def bulk_initiate(self, transfers, currency=None, source='balance'):
        return self._post('transfer/bulk', {'source': source, 'currency': currency, 'transfers': transfers})

    def list(self, **params):
        return self._get('transfer', **params)

    def fetch(self, id_or_code):
        return self._get(f'transfer/{_p(id_or_code)}')

    def verify(self, reference):
        return self._get(f'transfer/verify/{_p(reference)}')


class TransferControl(Resource):
    """https://paystack.com/docs/api/transfer-control/"""

    def balance(self):
        return self._get('balance')

    def ledger(self, **params):
        return self._get('balance/ledger', **params)

    def resend_otp(self, transfer_code, reason='transfer'):
        """reason: 'resend_otp' or 'transfer'."""
        return self._post('transfer/resend_otp', {'transfer_code': transfer_code, 'reason': reason})

    def disable_otp(self):
        return self._post('transfer/disable_otp')

    def finalize_disable_otp(self, otp):
        return self._post('transfer/disable_otp_finalize', {'otp': otp})

    def enable_otp(self):
        return self._post('transfer/enable_otp')


class BulkCharges(Resource):
    """https://paystack.com/docs/api/bulk-charge/"""

    def initiate(self, charges):
        """charges: list of {'authorization': ..., 'amount': ..., 'reference': ...}"""
        return self.client.request('POST', 'bulkcharge', json=charges)

    def list(self, **params):
        return self._get('bulkcharge', **params)

    def fetch(self, id_or_code):
        return self._get(f'bulkcharge/{_p(id_or_code)}')

    def charges(self, id_or_code, **params):
        return self._get(f'bulkcharge/{_p(id_or_code)}/charges', **params)

    def pause(self, batch_code):
        return self._get(f'bulkcharge/pause/{_p(batch_code)}')

    def resume(self, batch_code):
        return self._get(f'bulkcharge/resume/{_p(batch_code)}')


class Integration(Resource):
    """https://paystack.com/docs/api/integration/"""

    def fetch_timeout(self):
        return self._get('integration/payment_session_timeout')

    def update_timeout(self, timeout):
        return self._put('integration/payment_session_timeout', {'timeout': timeout})


class Charges(Resource):
    """https://paystack.com/docs/api/charge/ (direct charges: bank, USSD, mobile money, QR, card)"""

    def create(self, email, amount, reference=None, metadata=None, bank=None, bank_transfer=None, ussd=None,
               mobile_money=None, qr=None, authorization_code=None, pin=None, birthday=None, device_id=None,
               currency=None, **extra):
        return self._post('charge', {
            'email': email, 'amount': amount, 'reference': reference, 'metadata': metadata, 'bank': bank,
            'bank_transfer': bank_transfer, 'ussd': ussd, 'mobile_money': mobile_money, 'qr': qr,
            'authorization_code': authorization_code, 'pin': pin, 'birthday': birthday, 'device_id': device_id,
            'currency': currency, **extra,
        })

    def submit_pin(self, pin, reference):
        return self._post('charge/submit_pin', {'pin': pin, 'reference': reference})

    def submit_otp(self, otp, reference):
        return self._post('charge/submit_otp', {'otp': otp, 'reference': reference})

    def submit_phone(self, phone, reference):
        return self._post('charge/submit_phone', {'phone': phone, 'reference': reference})

    def submit_birthday(self, birthday, reference):
        return self._post('charge/submit_birthday', {'birthday': birthday, 'reference': reference})

    def submit_address(self, address, city, state, zipcode, reference):
        return self._post('charge/submit_address', {
            'address': address, 'city': city, 'state': state, 'zipcode': zipcode, 'reference': reference,
        })

    def check_pending(self, reference):
        return self._get(f'charge/{_p(reference)}')


class Disputes(Resource):
    """https://paystack.com/docs/api/dispute/"""

    def list(self, **params):
        return self._get('dispute', **params)

    def fetch(self, dispute_id):
        return self._get(f'dispute/{_p(dispute_id)}')

    def list_for_transaction(self, transaction_id):
        return self._get(f'dispute/transaction/{_p(transaction_id)}')

    def update(self, dispute_id, refund_amount, uploaded_filename=None):
        return self._put(f'dispute/{_p(dispute_id)}', {
            'refund_amount': refund_amount, 'uploaded_filename': uploaded_filename,
        })

    def add_evidence(self, dispute_id, customer_email, customer_name, customer_phone, service_details,
                     delivery_address=None, delivery_date=None):
        return self._post(f'dispute/{_p(dispute_id)}/evidence', {
            'customer_email': customer_email, 'customer_name': customer_name, 'customer_phone': customer_phone,
            'service_details': service_details, 'delivery_address': delivery_address,
            'delivery_date': delivery_date,
        })

    def upload_url(self, dispute_id, upload_filename):
        return self._get(f'dispute/{_p(dispute_id)}/upload_url', upload_filename=upload_filename)

    def resolve(self, dispute_id, resolution, message, refund_amount, uploaded_filename, evidence=None):
        """resolution: 'merchant-accepted' or 'declined'."""
        return self._put(f'dispute/{_p(dispute_id)}/resolve', {
            'resolution': resolution, 'message': message, 'refund_amount': refund_amount,
            'uploaded_filename': uploaded_filename, 'evidence': evidence,
        })

    def export(self, **params):
        return self._get('dispute/export', **params)


class Refunds(Resource):
    """https://paystack.com/docs/api/refund/"""

    def create(self, transaction, amount=None, currency=None, customer_note=None, merchant_note=None, **extra):
        return self._post('refund', {
            'transaction': transaction, 'amount': amount, 'currency': currency,
            'customer_note': customer_note, 'merchant_note': merchant_note, **extra,
        })

    def list(self, **params):
        return self._get('refund', **params)

    def fetch(self, refund_id):
        return self._get(f'refund/{_p(refund_id)}')


class Verification(Resource):
    """https://paystack.com/docs/api/verification/"""

    def resolve_account(self, account_number, bank_code):
        return self._get('bank/resolve', account_number=account_number, bank_code=bank_code)

    def validate_account(self, account_name, account_number, account_type, bank_code, country_code,
                         document_type, document_number=None):
        """Account validation for South African (and similar) accounts."""
        return self._post('bank/validate', {
            'account_name': account_name, 'account_number': account_number, 'account_type': account_type,
            'bank_code': bank_code, 'country_code': country_code, 'document_type': document_type,
            'document_number': document_number,
        })

    def resolve_card_bin(self, bin):
        return self._get(f'decision/bin/{_p(bin)}')


class Miscellaneous(Resource):
    """https://paystack.com/docs/api/miscellaneous/"""

    def list_banks(self, country=None, currency=None, use_cursor=None, per_page=None, pay_with_bank_transfer=None,
                   pay_with_bank=None, enabled_for_verification=None, type=None, **params):
        return self._get(
            'bank', country=country, currency=currency, use_cursor=use_cursor, perPage=per_page,
            pay_with_bank_transfer=pay_with_bank_transfer, pay_with_bank=pay_with_bank,
            enabled_for_verification=enabled_for_verification, type=type, **params,
        )

    def list_countries(self):
        return self._get('country')

    def list_states(self, country):
        return self._get('address_verification/states', country=country)
