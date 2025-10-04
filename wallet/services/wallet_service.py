from decimal import Decimal
import logging
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money
from wallet.models import Wallet, Transaction, Card, BankAccount, TransferRecipient
from wallet.exceptions import ( 
    TransactionFailed
)
from wallet.exceptions import InsufficientFunds
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT, TRANSACTION_TYPE_WITHDRAWAL, 
    TRANSACTION_TYPE_TRANSFER, TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS, TRANSACTION_STATUS_FAILED
)
from wallet.settings import get_wallet_setting
from wallet.services.paystack_service import PaystackService
from wallet.utils.id_generators import generate_transaction_reference

logger = logging.getLogger(__name__)


class WalletService:
    """
    Service for wallet operations
    """
    def __init__(self):
        self.paystack = PaystackService()
    
    def get_wallet(self, user):
        """
        Get or create a wallet for a user
        
        Args:
            user: User instance
            
        Returns:
            Wallet: User's wallet
        """
        wallet, created = Wallet.objects.get_or_create(user=user)
        
        if created:
            from wallet.utils.id_generators import generate_wallet_tag
            wallet.tag = generate_wallet_tag(user)
            wallet.save(update_fields=['tag'])
            
            # Create a Paystack customer
            try:
                customer_data = self.paystack.create_customer(
                    email=user.email,
                    first_name=getattr(user, 'first_name', None),
                    last_name=getattr(user, 'last_name', None),
                    phone=getattr(user, 'phone', None)
                )
                
                if customer_data and 'customer_code' in customer_data:
                    wallet.paystack_customer_code = customer_data['customer_code']
                    wallet.save(update_fields=['paystack_customer_code'])
                    
                    # Create a dedicated account for the customer
                    self.create_dedicated_account(wallet)
            except Exception as e:
                logger.error(f"Error creating Paystack customer for wallet {wallet.id}: {str(e)}")
        
        return wallet
    
    def create_dedicated_account(self, wallet):
        """
        Create a dedicated virtual account for a wallet
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not wallet.paystack_customer_code:
            logger.error(f"Cannot create dedicated account for wallet {wallet.id}: No Paystack customer code")
            return False
        
        try:
            account_data = self.paystack.create_dedicated_account(wallet.paystack_customer_code)
            
            if account_data and 'account_number' in account_data:
                wallet.dedicated_account_number = account_data['account_number']
                wallet.dedicated_account_bank = account_data.get('bank', {}).get('name')
                wallet.save(update_fields=['dedicated_account_number', 'dedicated_account_bank'])
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error creating dedicated account for wallet {wallet.id}: {str(e)}")
            return False
    
    def get_balance(self, wallet):
        """
        Get the current balance of a wallet
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            Money: Wallet balance
        """
        # Ensure we have the latest balance
        wallet.refresh_from_db(fields=['balance', 'balance_currency'])
        return wallet.balance
    
    @transaction.atomic
    def deposit(self, wallet, amount, description=None, metadata=None, transaction_reference=None):
        """
        Deposit funds into a wallet
        
        Args:
            wallet (Wallet): Wallet to deposit to
            amount (Decimal): Amount to deposit
            description (str, optional): Transaction description
            metadata (dict, optional): Additional transaction metadata
            transaction_reference (str, optional): Transaction reference
            
        Returns:
            Transaction: Created transaction
            
        Raises:
            WalletLocked: If the wallet is locked
            InvalidAmount: If the amount is invalid
        """
        if not description:
            description = _("Deposit to wallet")
        
        # Create pending transaction
        transaction = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=transaction_reference
        )
        
        try:
            # Add funds to wallet
            wallet.deposit(amount)
            
            # Update transaction
            transaction.status = TRANSACTION_STATUS_SUCCESS
            transaction.completed_at = timezone.now()
            transaction.save(update_fields=['status', 'completed_at'])
            
            return transaction
        except Exception as e:
            # Mark transaction as failed
            transaction.status = TRANSACTION_STATUS_FAILED
            transaction.failed_reason = str(e)
            transaction.save(update_fields=['status', 'failed_reason'])
            
            # Re-raise the exception
            raise
    
    @transaction.atomic
    def withdraw(self, wallet, amount, description=None, metadata=None, transaction_reference=None):
        """
        Withdraw funds from a wallet
        
        Args:
            wallet (Wallet): Wallet to withdraw from
            amount (Decimal): Amount to withdraw
            description (str, optional): Transaction description
            metadata (dict, optional): Additional transaction metadata
            transaction_reference (str, optional): Transaction reference
            
        Returns:
            Transaction: Created transaction
            
        Raises:
            WalletLocked: If the wallet is locked
            InvalidAmount: If the amount is invalid
            InsufficientFunds: If the wallet has insufficient funds
        """
        if not description:
            description = _("Withdrawal from wallet")
        
        # Create pending transaction
        transaction = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=transaction_reference
        )
        
        try:
            # Remove funds from wallet
            wallet.withdraw(amount)
            
            # Update transaction
            transaction.status = TRANSACTION_STATUS_SUCCESS
            transaction.completed_at = timezone.now()
            transaction.save(update_fields=['status', 'completed_at'])
            
            return transaction
        except Exception as e:
            # Mark transaction as failed
            transaction.status = TRANSACTION_STATUS_FAILED
            transaction.failed_reason = str(e)
            transaction.save(update_fields=['status', 'failed_reason'])
            
            # Re-raise the exception
            raise
    
    @transaction.atomic
    def transfer(self, source_wallet, destination_wallet, amount, description=None, 
                 metadata=None, transaction_reference=None):
        """
        Transfer funds between wallets
        
        Args:
            source_wallet (Wallet): Wallet to transfer from
            destination_wallet (Wallet): Wallet to transfer to
            amount (Decimal): Amount to transfer
            description (str, optional): Transaction description
            metadata (dict, optional): Additional transaction metadata
            transaction_reference (str, optional): Transaction reference
            
        Returns:
            Transaction: Created transaction
            
        Raises:
            WalletLocked: If either wallet is locked
            InvalidAmount: If the amount is invalid
            InsufficientFunds: If the source wallet has insufficient funds
        """
        if not description:
            description = _("Transfer to {recipient}").format(recipient=destination_wallet.user)
        
        # Create pending transaction
        transaction = Transaction.objects.create(
            wallet=source_wallet,
            recipient_wallet=destination_wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=transaction_reference
        )
        
        try:
            # Transfer funds between wallets
            source_wallet.transfer(destination_wallet, amount, description)
            
            # Update transaction
            transaction.status = TRANSACTION_STATUS_SUCCESS
            transaction.completed_at = timezone.now()
            transaction.save(update_fields=['status', 'completed_at'])
            
            return transaction
        except Exception as e:
            # Mark transaction as failed
            transaction.status = TRANSACTION_STATUS_FAILED
            transaction.failed_reason = str(e)
            transaction.save(update_fields=['status', 'failed_reason'])
            
            # Re-raise the exception
            raise
    
    def get_transaction_history(self, wallet, transaction_type=None, status=None, 
                               start_date=None, end_date=None):
        """
        Get transaction history for a wallet
        
        Args:
            wallet (Wallet): Wallet instance
            transaction_type (str, optional): Filter by transaction type
            status (str, optional): Filter by status
            start_date (datetime, optional): Filter by start date
            end_date (datetime, optional): Filter by end date
            
        Returns:
            QuerySet: Filtered transactions
        """
        transactions = Transaction.objects.filter(wallet=wallet)
        
        if transaction_type:
            transactions = transactions.filter(transaction_type=transaction_type)
        
        if status:
            transactions = transactions.filter(status=status)
        
        if start_date:
            transactions = transactions.filter(created_at__gte=start_date)
        
        if end_date:
            transactions = transactions.filter(created_at__lte=end_date)
        
        return transactions.order_by('-created_at')
    
    def initialize_card_charge(self, wallet, amount, email=None, reference=None, callback_url=None, metadata=None):
        """
        Initialize a card charge
        
        Args:
            wallet (Wallet): Wallet to deposit to
            amount (Decimal): Amount to charge
            email (str, optional): Customer email
            reference (str, optional): Unique transaction reference
            callback_url (str, optional): URL to redirect to after payment
            
        Returns:
            dict: Charge initialization data including authorization URL
        """
        # Ensure we have the customer's email
        if not email:
            email = wallet.user.email
        
        # Convert amount to kobo/cents
        amount_in_minor_unit = int(amount * 100)
        
       # Prepare metadata with required fields
        if metadata:
            metadata = metadata.copy()
        else:
            metadata = {}
        
        # Add required wallet and user information
        metadata.update({
            'wallet_id': str(wallet.id),
            'user_id': str(wallet.user.id)
        })
        
        return self.paystack.initialize_transaction(
            amount=amount_in_minor_unit,
            email=email,
            reference=reference,
            callback_url=callback_url,
            metadata=metadata
        )
    
    def verify_card_charge(self, reference):
        """
        Verify a card charge by reference
        
        Args:
            reference (str): Transaction reference
            
        Returns:
            dict: Transaction verification data
        """
        return self.paystack.verify_transaction(reference)
    

    @transaction.atomic
    def process_successful_card_charge(self, transaction_data):
        """
        Process a successful card charge
        
        Args:
            transaction_data (dict): Transaction data from Paystack
            
        Returns:
            tuple: (Wallet, Transaction, Card)
        """
        from wallet.models import Card
        
        # Extract data
        reference = transaction_data.get('reference') or generate_transaction_reference()
        amount_in_minor_unit = transaction_data.get('amount')
        metadata = transaction_data.get('metadata', {})
        description = metadata.get('description', 'Card deposit to wallet')
        wallet_id = metadata.get('wallet_id')
        ip_address = metadata.get("ip_address")
        channel = transaction_data.get("channel")
        user_agent = metadata.get("user_agent")
        # Calculate amount in major unit (e.g., naira)
        amount = Decimal(amount_in_minor_unit) / 100
        
        # Get the wallet
        try:
            wallet = Wallet.objects.get(id=wallet_id)
        except Wallet.DoesNotExist:
            raise TransactionFailed(_("Wallet not found"))
        
        # Create transaction
        transaction = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_SUCCESS,
            description=_(description),
            reference=reference,
            paystack_reference=reference,
            paystack_response=transaction_data,
            metadata=metadata,
            payment_method=channel,
            ip_address = ip_address,
            user_agent = user_agent,
            completed_at=timezone.now()
        )
        
        # Add funds to wallet
        wallet.deposit(amount)
        
        # Save card for future use if authorization is provided
        card = None
        authorization_data = transaction_data.get('authorization')
        
        if authorization_data and authorization_data.get('reusable'):
            # Format data
            card_type = authorization_data.get('card_type', '').strip().lower()
            last_four = authorization_data.get('last4', '')
            exp_month = authorization_data.get('exp_month', '')
            exp_year = authorization_data.get('exp_year', '')
            bin_number = authorization_data.get('bin', '')
            paystack_authorization_signature = authorization_data.get('signature', '')
            auth_code = authorization_data.get('authorization_code')
            
            # Check if card already exists
            existing_card = Card.objects.filter(
                wallet=wallet,
                paystack_authorization_code=auth_code
            ).first()
            
            if existing_card:
                # Update existing card
                card = existing_card
                card.last_four = last_four
                card.expiry_month = exp_month
                card.expiry_year = exp_year
                card.bin = bin_number
                card.is_active = True
                card.card_type = card_type
                card.paystack_authorization_signature = paystack_authorization_signature
                card.paystack_card_data = authorization_data
                card.save()
            else:
                # Create new card
                card = Card.objects.create(
                    wallet=wallet,
                    card_type=card_type,
                    last_four=last_four,
                    expiry_month=exp_month,
                    expiry_year=exp_year,
                    bin=bin_number,
                    card_holder_name=wallet.user.get_full_name() if hasattr(wallet.user, 'get_full_name') else None,
                    email=wallet.user.email,
                    paystack_authorization_signature = paystack_authorization_signature,
                    paystack_authorization_code=auth_code,
                    paystack_card_data=authorization_data
                )
                
                # Set as default if this is the first card
                if wallet.cards.count() == 1:
                    card.set_as_default()
            
            # Link card to transaction
            transaction.card = card
            transaction.save(update_fields=['card'])
        
        return wallet, transaction, card

    
    def charge_saved_card(self, card, amount, reference=None, metadata=None):
        """
        Charge a saved card
        
        Args:
            card (Card): Card to charge
            amount (Decimal): Amount to charge
            reference (str, optional): Unique transaction reference
            metadata (dict, optional): Additional transaction metadata
            
        Returns:
            dict: Charge data
        """
        # Convert amount to kobo/cents
        amount_in_minor_unit = int(amount * 100)
        
        # Add wallet metadata
        if metadata is None:
            metadata = {}
        
        metadata.update({
            'wallet_id': str(card.wallet.id),
            'user_id': str(card.wallet.user.id),
            'card_id': str(card.id)
        })
        
        # Charge the card
        return self.paystack.charge_authorization(
            amount=amount_in_minor_unit,
            email=card.email or card.wallet.user.email,
            authorization_code=card.paystack_authorization_code,
            reference=reference,
            metadata=metadata
        )
    
    def list_banks(self):
        """
        List available banks
        
        Returns:
            list: List of banks
        """
        return self.paystack.list_banks()
    
    def verify_bank_account(self, account_number, bank_code):
        """
        Verify bank account details
        
        Args:
            account_number (str): Account number
            bank_code (str): Bank code
            
        Returns:
            dict: Account verification data
        """
        return self.paystack.resolve_account_number(account_number, bank_code)
    
    @transaction.atomic
    def add_bank_account(self, wallet, bank_code, account_number, account_name=None, account_type=None):
        """
        Add a bank account to a wallet
        
        Args:
            wallet (Wallet): Wallet to add bank account to
            bank_code (str): Bank code
            account_number (str): Account number
            account_name (str, optional): Account name
            account_type (str, optional): Account type
            
        Returns:
            BankAccount: Created bank account
        """
        from wallet.models import Bank
        
        # Verify account details if name not provided
        if not account_name:
            account_data = self.verify_bank_account(account_number, bank_code)
            account_name = account_data.get('account_name')
            
            if not account_name:
                raise ValueError(_("Could not verify account details"))
        
        # Get or create bank
        bank, created = Bank.objects.get_or_create(
            code=bank_code,
            defaults={
                'name': '',  # Will be updated with real data later
                'slug': bank_code.lower()
            }
        )
        
        # If bank is new or missing name, try to fetch bank data
        if not bank.name:
            try:
                banks_list = self.list_banks()
                for bank_data in banks_list:
                    if bank_data.get('code') == bank_code:
                        bank.name = bank_data.get('name', '')
                        bank.slug = bank_data.get('slug', bank_code.lower())
                        bank.country = bank_data.get('country', 'NG')
                        bank.paystack_data = bank_data
                        bank.save()
                        break
            except Exception as e:
                logger.error(f"Error fetching bank data for code {bank_code}: {str(e)}")
                # Continue anyway, we'll just have a bank with an empty name
        
        # Create bank account
        bank_account = BankAccount.objects.create(
            wallet=wallet,
            bank=bank,
            account_number=account_number,
            account_name=account_name,
            account_type=account_type or BankAccount._meta.get_field('account_type').default
        )
        
        # Create Paystack transfer recipient
        try:
            recipient_data = self.paystack.create_transfer_recipient(
                account_type='nuban',
                name=account_name,
                account_number=account_number,
                bank_code=bank_code,
                currency=get_wallet_setting('CURRENCY'),
                description=f"Bank account for {wallet.user}"
            )
            
            if recipient_data and 'recipient_code' in recipient_data:
                # Save recipient code and mark as verified
                bank_account.paystack_recipient_code = recipient_data['recipient_code']
                bank_account.is_verified = True
                bank_account.paystack_data = recipient_data
                bank_account.save(update_fields=[
                    'paystack_recipient_code', 'is_verified', 'paystack_data'
                ])
                
                # Create transfer recipient record
                TransferRecipient.objects.create(
                    wallet=wallet,
                    recipient_code=recipient_data['recipient_code'],
                    type='nuban',
                    name=account_name,
                    account_number=account_number,
                    bank_code=bank_code,
                    bank_name=bank.name,
                    currency=get_wallet_setting('CURRENCY'),
                    paystack_data=recipient_data,
                    description = recipient_data.get('description', ''),
                    metadata=recipient_data.get('metadata', {}),
                    email=wallet.user.email,
                )
        except Exception as e:
            logger.error(f"Error creating transfer recipient for bank account {bank_account.id}: {str(e)}")
            # Continue anyway, we can try creating the recipient again later
        
        # Set as default if this is the first account
        if wallet.bank_accounts.count() == 1:
            bank_account.set_as_default()
        
        return bank_account
    
    @transaction.atomic
    def withdraw_to_bank(self, wallet, amount, bank_account, reason=None, metadata=None, reference=None):
        """
        Withdraw funds from wallet to a bank account
        
        Args:
            wallet (Wallet): Wallet to withdraw from
            amount (Decimal): Amount to withdraw
            bank_account (BankAccount): Bank account to withdraw to
            reason (str, optional): Reason for withdrawal
            metadata (dict, optional): Additional metadata
            reference (str, optional): Unique transfer reference
            
        Returns:
            tuple: (Transaction, transfer_data)
            
        Raises:
            WalletLocked: If the wallet is locked
            InvalidAmount: If the amount is invalid
            InsufficientFunds: If the wallet has insufficient funds
        """
        # Verify bank account has recipient code
        if not bank_account.paystack_recipient_code:
            raise ValueError(_("Bank account does not have a recipient code"))
        
        # Create description
        if not reason:
            reason = _("Withdrawal to bank account")
        
        # Convert amount to kobo/cents
        amount_in_minor_unit = int(amount * 100)
        
        # Create withdrawal transaction
        transaction = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING,
            description=reason,
            reference=reference,
            recipient_bank_account=bank_account,
            metadata=metadata or {},
            ip_address=metadata.get('ip_address', None),
            user_agent=metadata.get('user_agent', None)
        )
        
        try:
            # Withdraw from wallet
            wallet.withdraw(amount)
            
            # Initiate transfer to bank
            transfer_data = self.paystack.initiate_transfer(
                amount=amount_in_minor_unit,
                recipient_code=bank_account.paystack_recipient_code,
                reference= reference,
                reason=reason
            )
            
            # Update transaction with Paystack data
            transaction.paystack_reference = transfer_data.get('transfer_code')
            transaction.paystack_response = transfer_data
            # transaction.status = TRANSACTION_STATUS_SUCCESS if transfer_data.get('status') == 'success' else TRANSACTION_STATUS_PENDING
            
            # if transaction.status == TRANSACTION_STATUS_SUCCESS:
            #     transaction.completed_at = timezone.now()
                
            transaction.save()
            
            return transaction, transfer_data
        except Exception as e:
            # # Refund wallet if transfer failed
            # try:
            #     wallet.deposit(amount)
            # except Exception as refund_error:
            #     logger.error(f"Error refunding wallet after failed bank withdrawal: {str(refund_error)}")
            
            # # Mark transaction as failed
            # transaction.status = TRANSACTION_STATUS_FAILED
            # transaction.failed_reason = str(e)
            # transaction.save(update_fields=['status', 'failed_reason'])
            
            # # Re-raise the exception
            raise TransactionFailed(str(e), transaction.reference) from e
        
    def finalize_transfer(self, transfer_code, otp):
        """
        Finalize a transfer that requires OTP verification
        
        Args:
            transfer_code (str): The transfer code from the withdrawal
            otp (str): The OTP received by the user
            
        Returns:
            dict: Finalization response data
        """
        return self.paystack.finalize_transfer(transfer_code, otp)