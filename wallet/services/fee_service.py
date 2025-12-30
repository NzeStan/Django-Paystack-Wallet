"""
Fee Calculation Service

Handles all fee calculations for wallet transactions including:
- Deposit fees (card, DVA, USSD, etc.)
- Withdrawal/transfer fees
- Wallet-to-wallet transfer fees
- Fee bearer logic (customer, merchant, platform, split)
- Custom fee configurations from database
"""

import logging
from decimal import Decimal
from typing import Dict, Optional, Tuple, Any
from djmoney.money import Money

from wallet.settings import get_wallet_setting
from wallet.constants import (
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_WITHDRAWAL,
    TRANSACTION_TYPE_TRANSFER,
    FEE_BEARER_CUSTOMER,
    FEE_BEARER_MERCHANT,
    FEE_BEARER_PLATFORM,
    FEE_BEARER_SPLIT,
    PAYMENT_CHANNEL_LOCAL_CARD,
    PAYMENT_CHANNEL_INTL_CARD,
    PAYMENT_CHANNEL_DVA,
    PAYMENT_CHANNEL_BANK_TRANSFER,
)

logger = logging.getLogger(__name__)


class FeeCalculationResult:
    """
    Result object for fee calculations
    
    Attributes:
        original_amount: The original transaction amount
        fee_amount: Calculated fee amount
        net_amount: Amount after fee deduction (amount - fee)
        total_amount: Total amount to charge (amount + fee for customer bearer)
        bearer: Who bears the fee
        customer_pays: Amount customer needs to pay
        merchant_receives: Amount merchant receives in wallet
        fee_breakdown: Detailed breakdown of fee calculation
    """
    
    def __init__(
        self,
        original_amount: Money,
        fee_amount: Money,
        bearer: str,
        transaction_type: str
    ):
        self.original_amount = original_amount
        self.fee_amount = fee_amount
        self.bearer = bearer
        self.transaction_type = transaction_type
        
        # Calculate based on bearer
        self._calculate_amounts()
    
    def _calculate_amounts(self):
        """Calculate all amounts based on bearer logic"""
        currency = self.original_amount.currency
        
        if self.bearer == FEE_BEARER_CUSTOMER:
            # Customer pays amount + fee
            self.customer_pays = self.original_amount + self.fee_amount
            self.merchant_receives = self.original_amount
            self.net_amount = self.original_amount
            self.total_amount = self.customer_pays
            
        elif self.bearer == FEE_BEARER_MERCHANT:
            # Merchant receives amount - fee
            self.customer_pays = self.original_amount
            self.merchant_receives = self.original_amount - self.fee_amount
            self.net_amount = self.merchant_receives
            self.total_amount = self.original_amount
            
        elif self.bearer == FEE_BEARER_PLATFORM:
            # Platform absorbs fee, no change to amounts
            self.customer_pays = self.original_amount
            self.merchant_receives = self.original_amount
            self.net_amount = self.original_amount
            self.total_amount = self.original_amount
            
        elif self.bearer == FEE_BEARER_SPLIT:
            # Split fee between customer and merchant
            customer_percentage = get_wallet_setting('FEE_SPLIT_CUSTOMER_PERCENTAGE')
            merchant_percentage = get_wallet_setting('FEE_SPLIT_MERCHANT_PERCENTAGE')
            
            customer_fee = Money(
                (self.fee_amount.amount * Decimal(customer_percentage) / 100),
                currency
            )
            merchant_fee = Money(
                (self.fee_amount.amount * Decimal(merchant_percentage) / 100),
                currency
            )
            
            self.customer_pays = self.original_amount + customer_fee
            self.merchant_receives = self.original_amount - merchant_fee
            self.net_amount = self.merchant_receives
            self.total_amount = self.customer_pays
            
            self.split_details = {
                'customer_fee': customer_fee,
                'merchant_fee': merchant_fee,
                'customer_percentage': customer_percentage,
                'merchant_percentage': merchant_percentage
            }
        else:
            # Default to platform bearer
            self.customer_pays = self.original_amount
            self.merchant_receives = self.original_amount
            self.net_amount = self.original_amount
            self.total_amount = self.original_amount
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        result = {
            'original_amount': float(self.original_amount.amount),
            'fee_amount': float(self.fee_amount.amount),
            'net_amount': float(self.net_amount.amount),
            'total_amount': float(self.total_amount.amount),
            'currency': str(self.original_amount.currency),
            'bearer': self.bearer,
            'customer_pays': float(self.customer_pays.amount),
            'merchant_receives': float(self.merchant_receives.amount),
        }
        
        if hasattr(self, 'split_details'):
            result['split_details'] = {
                'customer_fee': float(self.split_details['customer_fee'].amount),
                'merchant_fee': float(self.split_details['merchant_fee'].amount),
                'customer_percentage': self.split_details['customer_percentage'],
                'merchant_percentage': self.split_details['merchant_percentage'],
            }
        
        return result


class FeeCalculator:
    """
    Main fee calculation service
    
    Handles all fee calculations with support for:
    - Percentage fees
    - Flat fees
    - Hybrid (percentage + flat) fees
    - Fee caps
    - Fee waivers based on thresholds
    - Multiple bearer models
    - Database-driven custom configurations
    """
    
    def __init__(self, wallet=None, user=None):
        """
        Initialize fee calculator
        
        Args:
            wallet: Wallet instance (for custom fee lookups)
            user: User instance (for custom fee lookups)
        """
        self.wallet = wallet
        self.user = user or (wallet.user if wallet else None)
        self.use_database_config = get_wallet_setting('USE_DATABASE_FEE_CONFIG')
    
    # ==========================================
    # PUBLIC METHODS
    # ==========================================
    
    def calculate_deposit_fee(
        self,
        amount: Money,
        payment_channel: str = PAYMENT_CHANNEL_LOCAL_CARD,
        is_international: bool = False,
        bearer: Optional[str] = None
    ) -> FeeCalculationResult:
        """
        Calculate fee for deposit transactions
        
        Args:
            amount: Deposit amount
            payment_channel: Payment channel (card, dva, ussd, etc.)
            is_international: Whether it's an international transaction
            bearer: Who bears the fee (customer, merchant, platform, split)
            
        Returns:
            FeeCalculationResult with all calculated amounts
        """
        if not get_wallet_setting('ENABLE_FEES'):
            return self._zero_fee_result(amount, bearer or get_wallet_setting('DEFAULT_FEE_BEARER'))
        
        # Check for custom database configuration
        if self.use_database_config and self.wallet:
            custom_fee = self._get_database_fee_config(
                transaction_type=TRANSACTION_TYPE_DEPOSIT,
                payment_channel=payment_channel
            )
            if custom_fee:
                fee_amount = self._calculate_from_config(amount, custom_fee)
                return FeeCalculationResult(
                    amount,
                    fee_amount,
                    bearer or custom_fee.get('bearer', get_wallet_setting('DEFAULT_FEE_BEARER')),
                    TRANSACTION_TYPE_DEPOSIT
                )
        
        # Use settings-based configuration
        if is_international or payment_channel == PAYMENT_CHANNEL_INTL_CARD:
            fee_amount = self._calculate_international_card_fee(amount)
        elif payment_channel == PAYMENT_CHANNEL_DVA:
            fee_amount = self._calculate_dva_fee(amount)
        else:
            # Default to local card/USSD fees
            fee_amount = self._calculate_local_card_fee(amount)
        
        return FeeCalculationResult(
            amount,
            fee_amount,
            bearer or get_wallet_setting('DEFAULT_FEE_BEARER'),
            TRANSACTION_TYPE_DEPOSIT
        )
    
    def calculate_withdrawal_fee(
        self,
        amount: Money,
        bearer: Optional[str] = None
    ) -> FeeCalculationResult:
        """
        Calculate fee for withdrawal/transfer to bank
        
        Uses tiered fee structure based on amount
        
        Args:
            amount: Withdrawal amount
            bearer: Who bears the fee (usually merchant or platform)
            
        Returns:
            FeeCalculationResult with all calculated amounts
        """
        if not get_wallet_setting('ENABLE_FEES') or not get_wallet_setting('ENABLE_TRANSFER_FEES'):
            return self._zero_fee_result(amount, bearer or get_wallet_setting('DEFAULT_FEE_BEARER'))
        
        # Check for custom database configuration
        if self.use_database_config and self.wallet:
            custom_fee = self._get_database_fee_config(
                transaction_type=TRANSACTION_TYPE_WITHDRAWAL
            )
            if custom_fee:
                fee_amount = self._calculate_from_config(amount, custom_fee)
                return FeeCalculationResult(
                    amount,
                    fee_amount,
                    bearer or custom_fee.get('bearer', FEE_BEARER_MERCHANT),
                    TRANSACTION_TYPE_WITHDRAWAL
                )
        
        # Use tiered fee structure
        fee_amount = self._calculate_tiered_transfer_fee(amount)
        
        return FeeCalculationResult(
            amount,
            fee_amount,
            bearer or FEE_BEARER_MERCHANT,  # Default: merchant bears withdrawal fees
            TRANSACTION_TYPE_WITHDRAWAL
        )
    
    def calculate_transfer_fee(
        self,
        amount: Money,
        bearer: Optional[str] = None
    ) -> FeeCalculationResult:
        """
        Calculate fee for wallet-to-wallet transfers
        
        Args:
            amount: Transfer amount
            bearer: Who bears the fee (sender, receiver, platform, split)
            
        Returns:
            FeeCalculationResult with all calculated amounts
        """
        if not get_wallet_setting('ENABLE_FEES') or not get_wallet_setting('ENABLE_INTERNAL_TRANSFER_FEES'):
            return self._zero_fee_result(amount, bearer or get_wallet_setting('DEFAULT_FEE_BEARER'))
        
        # Check for custom database configuration
        if self.use_database_config and self.wallet:
            custom_fee = self._get_database_fee_config(
                transaction_type=TRANSACTION_TYPE_TRANSFER
            )
            if custom_fee:
                fee_amount = self._calculate_from_config(amount, custom_fee)
                return FeeCalculationResult(
                    amount,
                    fee_amount,
                    bearer or custom_fee.get('bearer', get_wallet_setting('DEFAULT_FEE_BEARER')),
                    TRANSACTION_TYPE_TRANSFER
                )
        
        # Use settings-based configuration
        fee_amount = self._calculate_internal_transfer_fee(amount)
        
        return FeeCalculationResult(
            amount,
            fee_amount,
            bearer or get_wallet_setting('DEFAULT_FEE_BEARER'),
            TRANSACTION_TYPE_TRANSFER
        )
    
    def calculate_amount_with_fees(
        self,
        amount: Money,
        transaction_type: str,
        payment_channel: Optional[str] = None,
        is_international: bool = False,
        bearer: Optional[str] = None
    ) -> FeeCalculationResult:
        """
        Calculate total amount including fees
        
        This is useful when you want to know how much to charge a customer
        to ensure a specific amount is credited to the merchant
        
        Args:
            amount: Desired amount to be received
            transaction_type: Type of transaction
            payment_channel: Payment channel (for deposits)
            is_international: Whether international
            bearer: Who bears the fee
            
        Returns:
            FeeCalculationResult with all calculated amounts
        """
        if transaction_type == TRANSACTION_TYPE_DEPOSIT:
            return self.calculate_deposit_fee(
                amount, payment_channel or PAYMENT_CHANNEL_LOCAL_CARD, is_international, bearer
            )
        elif transaction_type == TRANSACTION_TYPE_WITHDRAWAL:
            return self.calculate_withdrawal_fee(amount, bearer)
        elif transaction_type == TRANSACTION_TYPE_TRANSFER:
            return self.calculate_transfer_fee(amount, bearer)
        else:
            return self._zero_fee_result(amount, bearer or get_wallet_setting('DEFAULT_FEE_BEARER'))
    
    # ==========================================
    # PRIVATE CALCULATION METHODS
    # ==========================================
    
    def _calculate_local_card_fee(self, amount: Money) -> Money:
        """
        Calculate local card/USSD fee (1.5% + NGN 100, capped at NGN 2000)
        
        Special rule: NGN 100 waived for transactions under NGN 2500
        """
        currency = amount.currency
        amount_value = amount.amount
        
        # Check for educational pricing
        if get_wallet_setting('ENABLE_EDUCATIONAL_PRICING'):
            percentage = Decimal(get_wallet_setting('EDUCATIONAL_CARD_PERCENTAGE_FEE')) / 100
            fee = amount_value * percentage
            cap = get_wallet_setting('EDUCATIONAL_CARD_FEE_CAP')
            return Money(min(fee, cap), currency)
        
        # Standard pricing
        percentage = Decimal(get_wallet_setting('LOCAL_CARD_PERCENTAGE_FEE')) / 100
        flat_fee = Decimal(get_wallet_setting('LOCAL_CARD_FLAT_FEE'))
        cap = Decimal(get_wallet_setting('LOCAL_CARD_FEE_CAP'))
        waiver_threshold = Decimal(get_wallet_setting('LOCAL_CARD_FEE_WAIVER_THRESHOLD'))
        
        # Calculate base fee
        percentage_fee = amount_value * percentage
        
        # Apply flat fee (unless waived)
        if amount_value < waiver_threshold:
            total_fee = percentage_fee  # Flat fee waived
        else:
            total_fee = percentage_fee + flat_fee
        
        # Apply cap
        total_fee = min(total_fee, cap)
        
        return Money(total_fee, currency)
    
    def _calculate_international_card_fee(self, amount: Money) -> Money:
        """
        Calculate international card fee (3.9% + NGN 100)
        """
        currency = amount.currency
        amount_value = amount.amount
        
        percentage = Decimal(get_wallet_setting('INTL_CARD_PERCENTAGE_FEE')) / 100
        flat_fee = Decimal(get_wallet_setting('INTL_CARD_FLAT_FEE'))
        
        fee = (amount_value * percentage) + flat_fee
        
        # Apply cap if set
        cap = get_wallet_setting('INTL_CARD_FEE_CAP')
        if cap:
            fee = min(fee, Decimal(cap))
        
        return Money(fee, currency)
    
    def _calculate_dva_fee(self, amount: Money) -> Money:
        """
        Calculate DVA (Dedicated Virtual Account) fee (1% capped at NGN 300)
        """
        currency = amount.currency
        amount_value = amount.amount
        
        percentage = Decimal(get_wallet_setting('DVA_PERCENTAGE_FEE')) / 100
        flat_fee = Decimal(get_wallet_setting('DVA_FLAT_FEE'))
        cap = Decimal(get_wallet_setting('DVA_FEE_CAP'))
        
        fee = (amount_value * percentage) + flat_fee
        fee = min(fee, cap)
        
        return Money(fee, currency)
    
    def _calculate_tiered_transfer_fee(self, amount: Money) -> Money:
        """
        Calculate tiered transfer fee based on amount ranges
        
        Default tiers (Paystack):
        - ≤ 5,000: NGN 10
        - 5,001 - 50,000: NGN 25
        - > 50,000: NGN 50
        """
        currency = amount.currency
        amount_value = amount.amount
        
        tiers = get_wallet_setting('TRANSFER_FEE_TIERS')
        
        for tier in tiers:
            max_amount = tier.get('max_amount')
            fee = tier.get('fee')
            
            if max_amount is None or amount_value <= Decimal(max_amount):
                return Money(fee, currency)
        
        # Fallback (should not reach here if tiers are configured correctly)
        return Money(50, currency)
    
    def _calculate_internal_transfer_fee(self, amount: Money) -> Money:
        """
        Calculate wallet-to-wallet transfer fee
        """
        currency = amount.currency
        amount_value = amount.amount
        
        percentage = Decimal(get_wallet_setting('INTERNAL_TRANSFER_PERCENTAGE_FEE')) / 100
        flat_fee = Decimal(get_wallet_setting('INTERNAL_TRANSFER_FLAT_FEE'))
        
        fee = (amount_value * percentage) + flat_fee
        
        # Apply cap if set
        cap = get_wallet_setting('INTERNAL_TRANSFER_FEE_CAP')
        if cap:
            fee = min(fee, Decimal(cap))
        
        return Money(fee, currency)
    
    def _calculate_from_config(self, amount: Money, config: Dict) -> Money:
        """
        Calculate fee from custom database configuration
        
        Args:
            amount: Transaction amount
            config: Database fee configuration
            
        Returns:
            Calculated fee amount
        """
        currency = amount.currency
        amount_value = amount.amount
        
        fee_type = config.get('fee_type')
        percentage = Decimal(config.get('percentage_fee', 0)) / 100
        flat_fee = Decimal(config.get('flat_fee', 0))
        cap = config.get('fee_cap')
        
        if fee_type == 'percentage':
            fee = amount_value * percentage
        elif fee_type == 'flat':
            fee = flat_fee
        else:  # hybrid
            fee = (amount_value * percentage) + flat_fee
        
        # Apply cap if set
        if cap:
            fee = min(fee, Decimal(cap))
        
        return Money(fee, currency)
    
    def _get_database_fee_config(
        self,
        transaction_type: str,
        payment_channel: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Retrieve custom fee configuration from database
        
        This method will be implemented when FeeConfiguration model is available
        
        Args:
            transaction_type: Type of transaction
            payment_channel: Payment channel (optional)
            
        Returns:
            Fee configuration dict or None
        """
        # TODO: Implement database lookup when FeeConfiguration model is ready
        # For now, return None to fallback to settings
        try:
            from wallet.models.fee_config import FeeConfiguration
            
            # Try to find specific config for wallet/user
            config = FeeConfiguration.objects.filter(
                wallet=self.wallet,
                transaction_type=transaction_type,
                payment_channel=payment_channel,
                is_active=True
            ).first()
            
            if config:
                return {
                    'fee_type': config.fee_type,
                    'percentage_fee': config.percentage_fee,
                    'flat_fee': config.flat_fee.amount if config.flat_fee else 0,
                    'fee_cap': config.fee_cap.amount if config.fee_cap else None,
                    'bearer': config.fee_bearer,
                }
            
            return None
            
        except ImportError:
            # Model not available yet
            return None
    
    def _zero_fee_result(self, amount: Money, bearer: str) -> FeeCalculationResult:
        """Return a zero-fee result"""
        return FeeCalculationResult(
            amount,
            Money(0, amount.currency),
            bearer,
            TRANSACTION_TYPE_DEPOSIT
        )


# ==========================================
# CONVENIENCE FUNCTIONS
# ==========================================

def calculate_fee(
    amount: Money,
    transaction_type: str,
    payment_channel: Optional[str] = None,
    is_international: bool = False,
    bearer: Optional[str] = None,
    wallet=None,
    user=None
) -> FeeCalculationResult:
    """
    Convenience function for fee calculation
    
    Args:
        amount: Transaction amount
        transaction_type: Type of transaction
        payment_channel: Payment channel (for deposits)
        is_international: Whether international
        bearer: Who bears the fee
        wallet: Wallet instance (optional)
        user: User instance (optional)
        
    Returns:
        FeeCalculationResult
    """
    calculator = FeeCalculator(wallet=wallet, user=user)
    return calculator.calculate_amount_with_fees(
        amount, transaction_type, payment_channel, is_international, bearer
    )