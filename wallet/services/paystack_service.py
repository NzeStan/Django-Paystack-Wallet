import requests
import json
import hmac
import hashlib
import logging
from urllib.parse import urljoin
from django.conf import settings

from wallet.settings import get_wallet_setting
from wallet.exceptions import PaystackAPIError, InvalidPaystackResponse, InvalidWebhookSignature


logger = logging.getLogger(__name__)


class PaystackService:
    """
    Service for interacting with Paystack API
    """
    def __init__(self):
        self.secret_key = get_wallet_setting('PAYSTACK_SECRET_KEY')
        self.public_key = get_wallet_setting('PAYSTACK_PUBLIC_KEY')
        self.api_url = get_wallet_setting('PAYSTACK_API_URL')
        
        # Ensure trailing slash for URL joining
        if not self.api_url.endswith('/'):
            self.api_url += '/'
    
    def _get_headers(self):
        """Get the default headers for Paystack API requests"""
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def _make_request(self, method, endpoint, **kwargs):
        """
        Make a request to the Paystack API
        
        Args:
            method (str): HTTP method to use (GET, POST, etc.)
            endpoint (str): API endpoint to call
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            dict: Response data
            
        Raises:
            PaystackAPIError: If the API returns an error
        """
        url = urljoin(self.api_url, endpoint)
        headers = self._get_headers()
        
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )
            
            # Handle response
            if response.status_code == 204:  # No content
                return {}
            
            try:
                response_data = response.json()
            except ValueError:
                raise InvalidPaystackResponse(response.text)
            
            # Check for Paystack error
            if not response_data.get('status'):
                message = response_data.get('message', 'Unknown error')
                raise PaystackAPIError(
                    message=message,
                    status_code=response.status_code,
                    response=response_data
                )
            
            return response_data.get('data', {})
            
        except requests.RequestException as e:
            logger.error(f"Paystack API request failed: {str(e)}")
            raise PaystackAPIError(message=str(e))
    
    def verify_webhook_signature(self, signature, payload):
        """
        Verify that a webhook came from Paystack
        
        Args:
            signature (str): X-Paystack-Signature header value
            payload (bytes): Raw request body
            
        Returns:
            bool: True if signature is valid, False otherwise
            
        Raises:
            InvalidWebhookSignature: If the signature is invalid
        """
        computed_hmac = hmac.new(
            key=self.secret_key.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha512
        ).hexdigest()
        
        if not hmac.compare_digest(computed_hmac, signature):
            raise InvalidWebhookSignature()
        
        return True
    
    # ---------- Charge API Methods ----------
    
    def initialize_transaction(self, amount, email, reference=None, callback_url=None, 
                               metadata=None, currency=None, channels=None):
        """
        Initialize a payment transaction
        
        Args:
            amount (int): Amount in kobo/cents
            email (str): Customer's email address
            reference (str, optional): Unique transaction reference
            callback_url (str, optional): URL to redirect to after payment
            metadata (dict, optional): Additional data to store with the transaction
            currency (str, optional): Transaction currency (default: NGN)
            channels (list, optional): Payment channels to allow
            
        Returns:
            dict: Transaction data including authorization URL
        """
        data = {
            'amount': amount,
            'email': email,
        }
        
        if reference:
            data['reference'] = reference
        
        if callback_url:
            data['callback_url'] = callback_url
            
        if metadata:
            data['metadata'] = metadata
            
        if currency:
            data['currency'] = currency
        
        if channels:
            data['channels'] = channels
            
        return self._make_request('POST', 'transaction/initialize', json=data)
    
    def verify_transaction(self, reference):
        """
        Verify a transaction by reference
        
        Args:
            reference (str): Transaction reference
            
        Returns:
            dict: Transaction verification data
        """
        return self._make_request('GET', f'transaction/verify/{reference}')
    
    def charge_authorization(self, amount, email, authorization_code, reference=None, 
                             metadata=None, currency=None):
        """
        Charge a previously authorized card
        
        Args:
            amount (int): Amount in kobo/cents
            email (str): Customer's email address
            authorization_code (str): Card authorization code
            reference (str, optional): Unique transaction reference
            metadata (dict, optional): Additional data to store with the transaction
            currency (str, optional): Transaction currency (default: NGN)
            
        Returns:
            dict: Charge data
        """
        data = {
            'amount': amount,
            'email': email,
            'authorization_code': authorization_code,
        }
        
        if reference:
            data['reference'] = reference
            
        if metadata:
            data['metadata'] = metadata
            
        if currency:
            data['currency'] = currency
            
        return self._make_request('POST', 'transaction/charge_authorization', json=data)
    
    # ---------- Transfer API Methods ----------
    
    def create_transfer_recipient(self, account_type, name, account_number=None, bank_code=None, 
                                  currency=None, description=None, metadata=None):
        """
        Create a transfer recipient
        
        Args:
            account_type (str): Type of recipient (nuban, mobile_money, etc.)
            name (str): Recipient's name
            account_number (str, optional): Account number (required for nuban)
            bank_code (str, optional): Bank code (required for nuban)
            currency (str, optional): Currency (default: NGN)
            description (str, optional): Description of recipient
            metadata (dict, optional): Additional data to store with the recipient
            
        Returns:
            dict: Recipient data
        """
        data = {
            'type': account_type,
            'name': name,
        }
        
        if account_type == 'nuban':
            if not account_number or not bank_code:
                raise ValueError("account_number and bank_code are required for nuban recipients")
            
            data['account_number'] = account_number
            data['bank_code'] = bank_code
        
        if currency:
            data['currency'] = currency
            
        if description:
            data['description'] = description
            
        if metadata:
            data['metadata'] = metadata
            
        return self._make_request('POST', 'transferrecipient', json=data)
    
    def initiate_transfer(self, amount, recipient_code, reference=None, reason=None, currency=None):
        """
        Initiate a transfer to a recipient
        
        Args:
            amount (int): Amount in kobo/cents
            recipient_code (str): Recipient code
            reference (str, optional): Unique transfer reference
            reason (str, optional): Reason for transfer
            currency (str, optional): Currency (default: NGN)
            
        Returns:
            dict: Transfer data
        """
        data = {
            'amount': amount,
            'recipient': recipient_code,
            'source': 'balance',
        }
        
        if reference:
            data['reference'] = reference
            
        if reason:
            data['reason'] = reason
            
        if currency:
            data['currency'] = currency
            
        return self._make_request('POST', 'transfer', json=data)
    
    def verify_transfer(self, reference):
        """
        Verify a transfer by reference
        
        Args:
            reference (str): Transfer reference
            
        Returns:
            dict: Transfer verification data
        """
        return self._make_request('GET', f'transfer/verify/{reference}')
    
    def finalize_transfer(self, transfer_code, otp):
        """
        Finalize a transfer that requires OTP verification
        
        Args:
            transfer_code (str): The transfer code from initiate_transfer
            otp (str): The OTP received by the user
            
        Returns:
            dict: Finalization response data
        """
        data = {
            'transfer_code': transfer_code,
            'otp': otp
        }
        
        return self._make_request('POST', 'transfer/finalize_transfer', json=data)

    # ---------- Dedicated Virtual Account API Methods ----------
    
    def create_dedicated_account(self, customer_id, preferred_bank=None, subaccount=None):
        """
        Create a dedicated virtual account for a customer
        
        Args:
            customer_id (str): Customer ID or code
            preferred_bank (str, optional): Preferred bank
            subaccount (str, optional): Subaccount code
            
        Returns:
            dict: Dedicated account data
        """
        data = {
            'customer': customer_id,
        }
        
        if preferred_bank:
            data['preferred_bank'] = preferred_bank
            
        if subaccount:
            data['subaccount'] = subaccount
            
        return self._make_request('POST', 'dedicated_account', json=data)
    
    def list_dedicated_accounts(self, customer_id=None, active=None, currency=None):
        """
        List dedicated virtual accounts
        
        Args:
            customer_id (str, optional): Filter by customer ID
            active (bool, optional): Filter by active status
            currency (str, optional): Filter by currency
            
        Returns:
            list: List of dedicated accounts
        """
        params = {}
        
        if customer_id:
            params['customer'] = customer_id
            
        if active is not None:
            params['active'] = 'true' if active else 'false'
            
        if currency:
            params['currency'] = currency
            
        return self._make_request('GET', 'dedicated_account', params=params)
    
    def deactivate_dedicated_account(self, dedicated_account_id):
        """
        Deactivate a dedicated virtual account
        
        Args:
            dedicated_account_id (int): Dedicated account ID
            
        Returns:
            dict: Deactivation result
        """
        return self._make_request('DELETE', f'dedicated_account/{dedicated_account_id}')
    
    # ---------- Customer API Methods ----------
    
    def create_customer(self, email, first_name=None, last_name=None, phone=None, metadata=None):
        """
        Create a new customer
        
        Args:
            email (str): Customer's email address
            first_name (str, optional): Customer's first name
            last_name (str, optional): Customer's last name
            phone (str, optional): Customer's phone number
            metadata (dict, optional): Additional data to store with the customer
            
        Returns:
            dict: Customer data
        """
        data = {
            'email': email,
        }
        
        if first_name:
            data['first_name'] = first_name
            
        if last_name:
            data['last_name'] = last_name
            
        if phone:
            data['phone'] = phone
            
        if metadata:
            data['metadata'] = metadata
            
        return self._make_request('POST', 'customer', json=data)
    
    def list_customers(self, email=None, page=None, per_page=None):
        """
        List customers
        
        Args:
            email (str, optional): Filter by email
            page (int, optional): Page number
            per_page (int, optional): Number of records per page
            
        Returns:
            list: List of customers
        """
        params = {}
        
        if email:
            params['email'] = email
            
        if page:
            params['page'] = page
            
        if per_page:
            params['perPage'] = per_page
            
        return self._make_request('GET', 'customer', params=params)
    
    def fetch_customer(self, customer_id):
        """
        Fetch a customer by ID
        
        Args:
            customer_id (int): Customer ID
            
        Returns:
            dict: Customer data
        """
        return self._make_request('GET', f'customer/{customer_id}')
    
    # ---------- Verification API Methods ----------
    
    def resolve_account_number(self, account_number, bank_code):
        """
        Resolve account number to account name
        
        Args:
            account_number (str): Account number
            bank_code (str): Bank code
            
        Returns:
            dict: Account resolution data
        """
        params = {
            'account_number': account_number,
            'bank_code': bank_code,
        }
        
        return self._make_request('GET', 'bank/resolve', params=params)
    
    def verify_bvn(self, bvn):
        """
        Verify a Bank Verification Number (BVN)
        
        Args:
            bvn (str): BVN to verify
            
        Returns:
            dict: BVN verification data
        """
        return self._make_request('GET', f'bvn/resolve/{bvn}')
    
    def list_banks(self, country='nigeria', currency=None, pay_with_bank_transfer=None):
        """
        List banks
        
        Args:
            country (str, optional): Country code
            currency (str, optional): Currency code
            pay_with_bank_transfer (bool, optional): Filter for pay with bank transfer
            
        Returns:
            list: List of banks
        """
        params = {
            'country': country,
        }
        
        if currency:
            params['currency'] = currency
            
        if pay_with_bank_transfer is not None:
            params['pay_with_bank_transfer'] = pay_with_bank_transfer
            
        return self._make_request('GET', 'bank', params=params)
    
    # ---------- Balance API Methods ----------
    
    def check_balance(self, currency=None):
        """
        Check account balance
        
        Args:
            currency (str, optional): Currency code
            
        Returns:
            dict: Balance data
        """
        endpoint = 'balance'
        
        if currency:
            endpoint = f'balance/{currency}'
            
        return self._make_request('GET', endpoint)
    
    def list_transactions(self, status=None, _from=None, to=None, amount=None, currency=None, 
                           customer=None, page=None, per_page=None):
        """
        List transactions
        
        Args:
            status (str, optional): Filter by status
            _from (str, optional): Filter by start date (YYYY-MM-DD)
            to (str, optional): Filter by end date (YYYY-MM-DD)
            amount (int, optional): Filter by amount in kobo/cents
            currency (str, optional): Filter by currency
            customer (str, optional): Filter by customer ID or email
            page (int, optional): Page number
            per_page (int, optional): Number of records per page
            
        Returns:
            list: List of transactions
        """
        params = {}
        
        if status:
            params['status'] = status
            
        if _from:
            params['from'] = _from
            
        if to:
            params['to'] = to
            
        if amount:
            params['amount'] = amount
            
        if currency:
            params['currency'] = currency
            
        if customer:
            params['customer'] = customer
            
        if page:
            params['page'] = page
            
        if per_page:
            params['perPage'] = per_page
            
        return self._make_request('GET', 'transaction', params=params)