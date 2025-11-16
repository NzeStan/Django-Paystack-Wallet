"""
Django Paystack Wallet - Wallet Service Layer (FIXED VERSION)
Fixed issues:
1. Added validation to prevent transfers to the same wallet
2. Modified transaction handling to persist failed transaction records
"""
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.money import Money

from wallet.models import Wallet, Transaction, Card, BankAccount, TransferRecipient, Bank
from wallet.exceptions import (
    BankAccountError
)
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED
)
from wallet.settings import get_wallet_setting
from wallet.services.paystack_service import PaystackService
from wallet.utils.id_generators import generate_transaction_reference, generate_wallet_tag


logger = logging.getLogger(__name__)


class WalletService:
    """
    Service layer for wallet operations
    
    This service encapsulates all business logic related to wallet operations,
    including deposits, withdrawals, transfers, and Paystack integrations.
    
    All monetary operations are wrapped in database transactions to ensure
    data consistency and integrity.
    """
    
    def __init__(self):
        """Initialize wallet service with Paystack integration"""
        self.paystack = PaystackService()
    
    # ==========================================
    # WALLET MANAGEMENT
    # ==========================================
    
    def get_wallet(self, user) -> Wallet:
        """
        Get or create a wallet for a user
        
        This method ensures every user has a wallet and sets up necessary
        Paystack integrations (customer code, dedicated virtual account).
        
        Args:
            user: User instance
            
        Returns:
            Wallet: User's wallet instance
            
        Raises:
            PaystackAPIError: If Paystack integration fails (non-critical)
        """
        wallet, created = Wallet.objects.select_related('user').get_or_create(
            user=user
        )
        
        if created:
            # Generate unique wallet tag
            wallet.tag = generate_wallet_tag(user)
            wallet.save(update_fields=['tag', 'updated_at'])
            
            logger.info(f"Created new wallet {wallet.id} for user {user.id}")
            
            # Set up Paystack customer
            self._setup_paystack_customer(wallet)
        
        return wallet
    
    def _setup_paystack_customer(self, wallet: Wallet) -> None:
        """
        Set up Paystack customer and dedicated account for wallet
        
        This is an internal method that handles Paystack customer creation
        and dedicated virtual account setup. Failures are logged but don't
        prevent wallet creation.
        
        Args:
            wallet (Wallet): Wallet instance to set up
        """
        try:
            # Create Paystack customer
            customer_data = self.paystack.create_customer(
                email=wallet.user.email,
                first_name=getattr(wallet.user, 'first_name', ''),
                last_name=getattr(wallet.user, 'last_name', ''),
                phone=getattr(wallet.user, 'phone', None)
            )
            
            if customer_data and 'customer_code' in customer_data:
                wallet.paystack_customer_code = customer_data['customer_code']
                wallet.save(update_fields=['paystack_customer_code', 'updated_at'])
                
                logger.info(
                    f"Created Paystack customer {wallet.paystack_customer_code} "
                    f"for wallet {wallet.id}"
                )
                
                # Create dedicated virtual account
                self.create_dedicated_account(wallet)
        
        except Exception as e:
            logger.error(
                f"Error setting up Paystack customer for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
    
    def create_dedicated_account(self, wallet: Wallet) -> bool:
        """
        Create a dedicated virtual account for a wallet
        
        Dedicated accounts allow users to fund their wallets via direct
        bank transfers to a unique account number.
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not wallet.paystack_customer_code:
            logger.error(
                f"Cannot create dedicated account for wallet {wallet.id}: "
                "No Paystack customer code"
            )
            return False
        
        try:
            account_data = self.paystack.create_dedicated_account(
                wallet.paystack_customer_code
            )
            
            if account_data and 'account_number' in account_data:
                wallet.dedicated_account_number = account_data['account_number']
                wallet.dedicated_account_bank = account_data.get('bank', {}).get('name')
                wallet.save(update_fields=[
                    'dedicated_account_number',
                    'dedicated_account_bank',
                    'updated_at'
                ])
                
                logger.info(
                    f"Created dedicated account {wallet.dedicated_account_number} "
                    f"for wallet {wallet.id}"
                )
                return True
            
            logger.warning(
                f"Incomplete account data received for wallet {wallet.id}: {account_data}"
            )
            return False
        
        except Exception as e:
            logger.error(
                f"Error creating dedicated account for wallet {wallet.id}: {str(e)}",
                exc_info=True
            )
            return False
    
    def get_balance(self, wallet: Wallet) -> Money:
        """
        Get the current balance of a wallet
        
        Args:
            wallet (Wallet): Wallet instance
            
        Returns:
            Money: Current wallet balance
        """
        # Refresh from database to ensure we have the latest balance
        wallet.refresh_from_db(fields=['balance', 'balance_currency'])
        return wallet.balance
    
    # ==========================================
    # DEPOSIT OPERATIONS
    # ==========================================
    
    def deposit(
        self,
        wallet: Wallet,
        amount: Decimal,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        transaction_reference: Optional[str] = None
    ) -> Transaction:
        """
        Deposit funds into a wallet
        
        This method creates a transaction record and updates the wallet balance.
        Uses a two-phase approach: create transaction first, then update balance
        in a nested transaction to ensure failed transactions are still recorded.
        
        Args:
            wallet (Wallet): Wallet to deposit into
            amount (Decimal): Amount to deposit
            description (str, optional): Transaction description
            metadata (dict, optional): Additional transaction metadata
            transaction_reference (str, optional): Custom transaction reference
            
        Returns:
            Transaction: Created transaction record
            
        Raises:
            WalletLocked: If wallet is locked or inactive
            InvalidAmount: If amount is invalid
        """
        if not description:
            description = _("Deposit to wallet")
        
        if not transaction_reference:
            transaction_reference = generate_transaction_reference()
        
        # Create pending transaction (outside the atomic block to persist even on failure)
        txn = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_DEPOSIT,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=transaction_reference
        )
        
        logger.info(
            f"Created deposit transaction {txn.id} for wallet {wallet.id}: "
            f"amount={amount}, reference={transaction_reference}"
        )
        
        try:
            # Use atomic block for the balance update
            with transaction.atomic():
                # Add funds to wallet
                wallet.deposit(amount)
            
            # Mark transaction as successful
            txn.status = TRANSACTION_STATUS_SUCCESS
            txn.completed_at = timezone.now()
            txn.save(update_fields=['status', 'completed_at', 'updated_at'])
            
            logger.info(f"Deposit transaction {txn.id} completed successfully")
            
            return txn
        
        except Exception as e:
            # Mark transaction as failed
            txn.status = TRANSACTION_STATUS_FAILED
            txn.failed_reason = str(e)
            txn.save(update_fields=['status', 'failed_reason', 'updated_at'])
            
            logger.error(
                f"Deposit transaction {txn.id} failed: {str(e)}",
                exc_info=True
            )
            
            # Re-raise the exception
            raise
    
    def initialize_card_charge(
        self,
        wallet: Wallet,
        amount: Decimal,
        email: Optional[str] = None,
        reference: Optional[str] = None,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Initialize a Paystack card charge
        
        This generates a payment link that users can use to fund their wallet
        via card payment through Paystack's payment gateway.
        
        Args:
            wallet (Wallet): Wallet to deposit into
            amount (Decimal): Amount to charge
            email (str, optional): Customer email (defaults to user's email)
            reference (str, optional): Transaction reference
            callback_url (str, optional): URL to redirect after payment
            metadata (dict, optional): Additional metadata
            
        Returns:
            dict: Charge initialization data with authorization URL
            
        Raises:
            PaystackAPIError: If Paystack API call fails
        """
        # Ensure we have the customer's email
        email = email or wallet.user.email
        
        if not email:
            raise ValueError(_("Email is required for card charge"))
        
        # Generate reference if not provided
        if not reference:
            reference = generate_transaction_reference()
        
        # Convert amount to minor units (kobo/cents)
        amount_in_minor_unit = int(Decimal(amount) * 100)
        
        # Prepare metadata
        charge_metadata = metadata.copy() if metadata else {}
        charge_metadata.update({
            'wallet_id': str(wallet.id),
            'user_id': str(wallet.user.id),
            'transaction_type': 'wallet_deposit'
        })
        
        logger.info(
            f"Initializing card charge for wallet {wallet.id}: "
            f"amount={amount}, reference={reference}"
        )
        
        # Initialize transaction with Paystack
        charge_data = self.paystack.initialize_transaction(
            amount=amount_in_minor_unit,
            email=email,
            reference=reference,
            callback_url=callback_url,
            metadata=charge_metadata
        )
        
        logger.info(
            f"Card charge initialized for wallet {wallet.id}: "
            f"reference={reference}, access_code={charge_data.get('access_code')}"
        )
        
        return charge_data
    
    # ==========================================
    # WITHDRAWAL OPERATIONS
    # ==========================================
    
    def withdraw(
        self,
        wallet: Wallet,
        amount: Decimal,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        transaction_reference: Optional[str] = None
    ) -> Transaction:
        """
        Withdraw funds from a wallet
        
        This method creates a transaction record and updates the wallet balance.
        Uses a two-phase approach: create transaction first, then update balance
        in a nested transaction to ensure failed transactions are still recorded.
        
        Args:
            wallet (Wallet): Wallet to withdraw from
            amount (Decimal): Amount to withdraw
            description (str, optional): Transaction description
            metadata (dict, optional): Additional transaction metadata
            transaction_reference (str, optional): Custom transaction reference
            
        Returns:
            Transaction: Created transaction record
            
        Raises:
            WalletLocked: If wallet is locked or inactive
            InvalidAmount: If amount is invalid
            InsufficientFunds: If wallet has insufficient funds
        """
        if not description:
            description = _("Withdrawal from wallet")
        
        if not transaction_reference:
            transaction_reference = generate_transaction_reference()
        
        # Create pending transaction (outside the atomic block to persist even on failure)
        txn = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=transaction_reference
        )
        
        logger.info(
            f"Created withdrawal transaction {txn.id} for wallet {wallet.id}: "
            f"amount={amount}, reference={transaction_reference}"
        )
        
        try:
            # Use atomic block for the balance update
            with transaction.atomic():
                # Remove funds from wallet
                wallet.withdraw(amount)
            
            # Mark transaction as successful
            txn.status = TRANSACTION_STATUS_SUCCESS
            txn.completed_at = timezone.now()
            txn.save(update_fields=['status', 'completed_at', 'updated_at'])
            
            logger.info(f"Withdrawal transaction {txn.id} completed successfully")
            
            return txn
        
        except Exception as e:
            # Mark transaction as failed
            txn.status = TRANSACTION_STATUS_FAILED
            txn.failed_reason = str(e)
            txn.save(update_fields=['status', 'failed_reason', 'updated_at'])
            
            logger.error(
                f"Withdrawal transaction {txn.id} failed: {str(e)}",
                exc_info=True
            )
            
            # Re-raise the exception
            raise

    def withdraw_to_bank(
        self,
        wallet: Wallet,
        amount: Decimal,
        bank_account: BankAccount,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None
    ) -> Tuple[Transaction, Dict[str, Any]]:
        """
        Withdraw funds from wallet to a bank account
        
        This initiates a bank transfer via Paystack and creates a withdrawal
        transaction. Uses a two-phase approach: create transaction first, 
        then update balance in a nested transaction to ensure failed 
        transactions are still recorded.
        
        Args:
            wallet (Wallet): Wallet to withdraw from
            amount (Decimal): Amount to withdraw
            bank_account (BankAccount): Bank account to transfer to
            reason (str, optional): Transfer reason
            metadata (dict, optional): Additional metadata
            reference (str, optional): Transfer reference
            
        Returns:
            tuple: (Transaction, transfer_data from Paystack)
            
        Raises:
            WalletLocked: If wallet is locked or inactive
            InvalidAmount: If amount is invalid
            InsufficientFunds: If wallet has insufficient funds
            BankAccountError: If bank account is invalid
            PaystackAPIError: If Paystack transfer fails
        """
        # Verify bank account has recipient code
        if not bank_account.paystack_recipient_code:
            raise BankAccountError(
                "Bank account does not have a recipient code",
                account_id=bank_account.id
            )
        
        # Verify bank account belongs to this wallet
        if bank_account.wallet_id != wallet.id:
            raise BankAccountError(
                "Bank account does not belong to this wallet",
                account_id=bank_account.id
            )
        
        # Create description
        if not reason:
            reason = _("Withdrawal to bank account")
        
        # Generate reference if not provided
        if not reference:
            reference = generate_transaction_reference()
        
        # Convert amount to minor units
        amount_in_minor_unit = int(Decimal(amount) * 100)
        
        # Create withdrawal transaction (outside atomic block to persist even on failure)
        txn = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_WITHDRAWAL,
            status=TRANSACTION_STATUS_PENDING,
            description=reason,
            metadata=metadata or {},
            reference=reference,
            recipient_bank_account=bank_account
        )
        
        logger.info(
            f"Created bank withdrawal transaction {txn.id} for wallet {wallet.id}: "
            f"amount={amount}, bank_account={bank_account.id}, reference={reference}"
        )
        
        try:
            # Initiate Paystack transfer (outside atomic block - API call)
            transfer_data = self.paystack.initiate_transfer(
                amount=amount_in_minor_unit,
                recipient=bank_account.paystack_recipient_code,
                reason=reason,
                reference=reference
            )
            
            # Use atomic block only for the wallet balance update
            with transaction.atomic():
                # Withdraw from wallet
                wallet.withdraw(amount)
            
            # Update transaction with Paystack data (outside atomic block)
            txn.paystack_reference = transfer_data.get('transfer_code')
            txn.paystack_response = transfer_data
            txn.status = TRANSACTION_STATUS_SUCCESS
            txn.completed_at = timezone.now()
            txn.save(update_fields=[
                'paystack_reference',
                'paystack_response',
                'status',
                'completed_at',
                'updated_at'
            ])
            
            logger.info(
                f"Bank withdrawal {txn.id} initiated successfully: "
                f"transfer_code={transfer_data.get('transfer_code')}"
            )
            
            return txn, transfer_data
        
        except Exception as e:
            # Mark transaction as failed (outside atomic block, so it persists)
            txn.status = TRANSACTION_STATUS_FAILED
            txn.failed_reason = str(e)
            txn.save(update_fields=['status', 'failed_reason', 'updated_at'])
            
            logger.error(
                f"Bank withdrawal transaction {txn.id} failed: {str(e)}",
                exc_info=True
            )
            
            # Re-raise the exception
            raise
    
    
    
    # ==========================================
    # TRANSFER OPERATIONS
    # ==========================================
    
    @transaction.atomic
    def transfer(
        self,
        source_wallet: Wallet,
        destination_wallet: Wallet,
        amount: Decimal,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        transaction_reference: Optional[str] = None
    ) -> Transaction:
        """
        Transfer funds between wallets
        
        This creates a transfer transaction and moves funds from source to
        destination wallet. The operation is atomic - either both wallets
        are updated or neither is.
        
        Args:
            source_wallet (Wallet): Wallet to transfer from
            destination_wallet (Wallet): Wallet to transfer to
            amount (Decimal): Amount to transfer
            description (str, optional): Transfer description
            metadata (dict, optional): Additional metadata
            transaction_reference (str, optional): Transaction reference
            
        Returns:
            Transaction: Created transaction record
            
        Raises:
            WalletLocked: If either wallet is locked or inactive
            InvalidAmount: If amount is invalid
            InsufficientFunds: If source wallet has insufficient funds
            ValueError: If source and destination wallets are the same
        """
        # FIX #1: Validate that source and destination are different
        if source_wallet.id == destination_wallet.id:
            raise ValueError(_("Cannot transfer to the same wallet"))
        
        # Default description
        if not description:
            destination_user = getattr(destination_wallet.user, 'email', str(destination_wallet.user))
            description = _("Transfer to {recipient}").format(recipient=destination_user)
        
        if not transaction_reference:
            transaction_reference = generate_transaction_reference()
        
        # Create pending transaction
        txn = Transaction.objects.create(
            wallet=source_wallet,
            recipient_wallet=destination_wallet,
            amount=amount,
            transaction_type=TRANSACTION_TYPE_TRANSFER,
            status=TRANSACTION_STATUS_PENDING,
            description=description,
            metadata=metadata or {},
            reference=transaction_reference
        )
        
        logger.info(
            f"Created transfer transaction {txn.id}: "
            f"from_wallet={source_wallet.id}, to_wallet={destination_wallet.id}, "
            f"amount={amount}, reference={transaction_reference}"
        )
        
        try:
            # Execute transfer
            source_wallet.transfer(destination_wallet, amount, description)
            
            # Mark transaction as successful
            txn.status = TRANSACTION_STATUS_SUCCESS
            txn.completed_at = timezone.now()
            txn.save(update_fields=['status', 'completed_at', 'updated_at'])
            
            logger.info(f"Transfer transaction {txn.id} completed successfully")
            
            return txn
        
        except Exception as e:
            # Mark transaction as failed
            txn.status = TRANSACTION_STATUS_FAILED
            txn.failed_reason = str(e)
            txn.save(update_fields=['status', 'failed_reason', 'updated_at'])
            
            logger.error(
                f"Transfer transaction {txn.id} failed: {str(e)}",
                exc_info=True
            )
            
            # Re-raise the exception
            raise
    
    # ==========================================
    # CARD OPERATIONS
    # ==========================================
    
    def charge_saved_card(
        self,
        card: Card,
        amount: Decimal,
        reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Charge a saved card
        
        This charges a previously saved card using its authorization code.
        Useful for recurring payments or quick checkouts.
        
        Args:
            card (Card): Card to charge
            amount (Decimal): Amount to charge
            reference (str, optional): Transaction reference
            metadata (dict, optional): Additional metadata
            
        Returns:
            dict: Charge response data from Paystack
            
        Raises:
            PaystackAPIError: If charge fails
        """
        # Generate reference if not provided
        if not reference:
            reference = generate_transaction_reference()
        
        # Convert amount to minor units
        amount_in_minor_unit = int(Decimal(amount) * 100)
        
        # Prepare metadata
        charge_metadata = metadata.copy() if metadata else {}
        charge_metadata.update({
            'wallet_id': str(card.wallet.id),
            'user_id': str(card.wallet.user.id),
            'card_id': str(card.id)
        })
        
        # Get email for the charge
        email = card.email or card.wallet.user.email
        
        logger.info(
            f"Charging saved card {card.id} for wallet {card.wallet.id}: "
            f"amount={amount}, reference={reference}"
        )
        
        # Charge the card via Paystack
        charge_data = self.paystack.charge_authorization(
            amount=amount_in_minor_unit,
            email=email,
            authorization_code=card.paystack_authorization_code,
            reference=reference,
            metadata=charge_metadata
        )
        
        logger.info(
            f"Card {card.id} charged: reference={reference}, "
            f"status={charge_data.get('status')}"
        )
        
        return charge_data
    
    # ==========================================
    # BANK ACCOUNT OPERATIONS
    # ==========================================
    
    def list_banks(self) -> list:
        """
        List available banks
        
        Returns:
            list: List of bank dictionaries from Paystack
        """
        return self.paystack.list_banks()
    
    def verify_bank_account(
        self,
        account_number: str,
        bank_code: str
    ) -> Dict[str, Any]:
        """
        Verify bank account details
        
        Args:
            account_number (str): Account number
            bank_code (str): Bank code
            
        Returns:
            dict: Account verification data
            
        Raises:
            PaystackAPIError: If verification fails
        """
        return self.paystack.resolve_account_number(account_number, bank_code)
    
    @transaction.atomic
    def add_bank_account(
        self,
        wallet: Wallet,
        bank_code: str,
        account_number: str,
        account_name: Optional[str] = None,
        account_type: Optional[str] = None,
        bvn: Optional[str] = None
    ) -> BankAccount:
        """
        Add a bank account to a wallet
        
        This verifies the account with Paystack, creates a transfer recipient,
        and stores the bank account details.
        
        Args:
            wallet (Wallet): Wallet to add account to
            bank_code (str): Bank code
            account_number (str): Account number
            account_name (str, optional): Account holder name
            account_type (str, optional): Account type
            bvn (str, optional): Bank Verification Number
            
        Returns:
            BankAccount: Created bank account instance
            
        Raises:
            BankAccountError: If account verification or creation fails
        """
        # Verify account details if name not provided
        if not account_name:
            try:
                account_data = self.verify_bank_account(account_number, bank_code)
                account_name = account_data.get('account_name')
                
                if not account_name:
                    raise BankAccountError("Could not verify account name")
            
            except Exception as e:
                logger.error(f"Account verification failed: {str(e)}")
                raise BankAccountError(f"Account verification failed: {str(e)}")
        
        # Get bank details
        try:
            bank = Bank.objects.get(code=bank_code)
        except Bank.DoesNotExist:
            raise BankAccountError(f"Bank with code {bank_code} not found")
        
        # Prepare data for bank account creation
        bank_account_data = {
            'wallet': wallet,
            'bank': bank,
            'account_number': account_number,
            'account_name': account_name,
            'is_verified': True
        }
        
        # Only add account_type if it's provided (otherwise use model default)
        if account_type:
            bank_account_data['account_type'] = account_type
        
        # Create bank account
        bank_account = BankAccount.objects.create(**bank_account_data)
        
        logger.info(
            f"Created bank account {bank_account.id} for wallet {wallet.id}: "
            f"{bank.name} - {account_number}"
        )
        
        # Create Paystack transfer recipient
        try:
            recipient_data = self.paystack.create_transfer_recipient(
                account_number=account_number,
                bank_code=bank_code,
                name=account_name,
                currency=get_wallet_setting('CURRENCY')
            )
            
            if recipient_data and 'recipient_code' in recipient_data:
                # Save recipient code to bank account
                bank_account.paystack_recipient_code = recipient_data['recipient_code']
                bank_account.save(update_fields=['paystack_recipient_code', 'updated_at'])
                
                # Also create TransferRecipient record
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
                    description=recipient_data.get('description', ''),
                    metadata=recipient_data.get('metadata', {}),
                    email=wallet.user.email
                )
                
                logger.info(
                    f"Created transfer recipient for bank account {bank_account.id}: "
                    f"{recipient_data['recipient_code']}"
                )
        
        except Exception as e:
            logger.error(
                f"Error creating transfer recipient for bank account {bank_account.id}: {str(e)}",
                exc_info=True
            )
            # Continue anyway - we can create recipient later
        
        # Set as default if this is the first account
        if wallet.bank_accounts.count() == 1:
            bank_account.set_as_default()
        
        return bank_account
    
    # ==========================================
    # TRANSACTION HISTORY
    # ==========================================
    
    def get_transaction_history(
        self,
        wallet: Wallet,
        transaction_type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None
    ):
        """
        Get transaction history for a wallet
        
        This method provides filtered access to a wallet's transaction history
        with query optimization using select_related and prefetch_related.
        
        Args:
            wallet (Wallet): Wallet instance
            transaction_type (str, optional): Filter by transaction type
            status (str, optional): Filter by status
            start_date (datetime, optional): Filter by start date
            end_date (datetime, optional): Filter by end date
            
        Returns:
            QuerySet: Filtered and optimized transaction queryset
        """
        # Start with optimized base query
        transactions = Transaction.objects.filter(wallet=wallet).select_related(
            'wallet__user',
            'recipient_wallet__user',
            'recipient_bank_account__bank',
            'card'
        )
        
        # Apply filters
        if transaction_type:
            transactions = transactions.filter(transaction_type=transaction_type)
        
        if status:
            transactions = transactions.filter(status=status)
        
        if start_date:
            transactions = transactions.filter(created_at__gte=start_date)
        
        if end_date:
            transactions = transactions.filter(created_at__lte=end_date)
        
        # Order by most recent first
        return transactions.order_by('-created_at')