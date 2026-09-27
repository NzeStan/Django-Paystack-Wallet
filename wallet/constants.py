from django.utils.translation import gettext_lazy as _

# ==========================================
# CURRENCIES SUPPORTED BY PAYSTACK
# ==========================================

SUPPORTED_CURRENCIES = (
    ('NGN', _('Nigerian Naira')),
    ('GHS', _('Ghanaian Cedi')),
    ('ZAR', _('South African Rand')),
    ('KES', _('Kenyan Shilling')),
    ('USD', _('US Dollar')),
    ('XOF', _('West African CFA Franc')),
    ('EGP', _('Egyptian Pound')),
    ('RWF', _('Rwandan Franc')),
)

# ==========================================
# TRANSACTIONS
# ==========================================

TRANSACTION_TYPE_DEPOSIT = 'deposit'
TRANSACTION_TYPE_WITHDRAWAL = 'withdrawal'
TRANSACTION_TYPE_TRANSFER = 'transfer'
TRANSACTION_TYPE_PAYMENT = 'payment'
TRANSACTION_TYPE_REFUND = 'refund'
TRANSACTION_TYPE_REVERSAL = 'reversal'
TRANSACTION_TYPE_FEE = 'fee'
TRANSACTION_TYPE_COMMISSION = 'commission'

TRANSACTION_TYPES = (
    (TRANSACTION_TYPE_DEPOSIT, _('Deposit')),
    (TRANSACTION_TYPE_WITHDRAWAL, _('Withdrawal')),
    (TRANSACTION_TYPE_TRANSFER, _('Transfer')),
    (TRANSACTION_TYPE_PAYMENT, _('Payment')),
    (TRANSACTION_TYPE_REFUND, _('Refund')),
    (TRANSACTION_TYPE_REVERSAL, _('Reversal')),
    (TRANSACTION_TYPE_FEE, _('Fee')),
    (TRANSACTION_TYPE_COMMISSION, _('Commission')),
)

TRANSACTION_STATUS_PENDING = 'pending'
TRANSACTION_STATUS_PROCESSING = 'processing'
TRANSACTION_STATUS_SUCCESS = 'success'
TRANSACTION_STATUS_FAILED = 'failed'
TRANSACTION_STATUS_CANCELLED = 'cancelled'
TRANSACTION_STATUS_REVERSED = 'reversed'

TRANSACTION_STATUSES = (
    (TRANSACTION_STATUS_PENDING, _('Pending')),
    (TRANSACTION_STATUS_PROCESSING, _('Processing')),
    (TRANSACTION_STATUS_SUCCESS, _('Success')),
    (TRANSACTION_STATUS_FAILED, _('Failed')),
    (TRANSACTION_STATUS_CANCELLED, _('Cancelled')),
    (TRANSACTION_STATUS_REVERSED, _('Reversed')),
)

# Statuses from which a transaction can no longer change
FINAL_TRANSACTION_STATUSES = (
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_CANCELLED,
    TRANSACTION_STATUS_REVERSED,
)

# Direction of the balance movement on the transaction's own wallet
DIRECTION_CREDIT = 'credit'
DIRECTION_DEBIT = 'debit'

TRANSACTION_DIRECTIONS = (
    (DIRECTION_CREDIT, _('Credit')),
    (DIRECTION_DEBIT, _('Debit')),
)

# ==========================================
# PAYMENT METHODS (how money entered/left)
# ==========================================

PAYMENT_METHOD_CARD = 'card'
PAYMENT_METHOD_BANK = 'bank'
PAYMENT_METHOD_USSD = 'ussd'
PAYMENT_METHOD_QR = 'qr'
PAYMENT_METHOD_MOBILE_MONEY = 'mobile_money'
PAYMENT_METHOD_BANK_TRANSFER = 'bank_transfer'
PAYMENT_METHOD_WALLET = 'wallet'
PAYMENT_METHOD_DVA = 'dva'
PAYMENT_METHOD_EFT = 'eft'
PAYMENT_METHOD_APPLE_PAY = 'apple_pay'
PAYMENT_METHOD_PAYATTITUDE = 'payattitude'

PAYMENT_METHODS = (
    (PAYMENT_METHOD_CARD, _('Card')),
    (PAYMENT_METHOD_BANK, _('Bank')),
    (PAYMENT_METHOD_USSD, _('USSD')),
    (PAYMENT_METHOD_QR, _('QR Code')),
    (PAYMENT_METHOD_MOBILE_MONEY, _('Mobile Money')),
    (PAYMENT_METHOD_BANK_TRANSFER, _('Bank Transfer')),
    (PAYMENT_METHOD_WALLET, _('Wallet')),
    (PAYMENT_METHOD_DVA, _('Dedicated Virtual Account')),
    (PAYMENT_METHOD_EFT, _('EFT')),
    (PAYMENT_METHOD_APPLE_PAY, _('Apple Pay')),
    (PAYMENT_METHOD_PAYATTITUDE, _('PayAttitude')),
)

# Paystack checkout channels (values accepted by transaction/initialize `channels`)
PAYSTACK_CHANNELS = (
    'card', 'bank', 'ussd', 'qr', 'mobile_money', 'bank_transfer', 'eft', 'apple_pay', 'payattitude',
)

# Paystack `channel` value on a charge -> our payment method
PAYSTACK_CHANNEL_TO_PAYMENT_METHOD = {
    'card': PAYMENT_METHOD_CARD,
    'bank': PAYMENT_METHOD_BANK,
    'ussd': PAYMENT_METHOD_USSD,
    'qr': PAYMENT_METHOD_QR,
    'mobile_money': PAYMENT_METHOD_MOBILE_MONEY,
    'bank_transfer': PAYMENT_METHOD_BANK_TRANSFER,
    'dedicated_nuban': PAYMENT_METHOD_DVA,
    'eft': PAYMENT_METHOD_EFT,
    'apple_pay': PAYMENT_METHOD_APPLE_PAY,
    'payattitude': PAYMENT_METHOD_PAYATTITUDE,
}

# ==========================================
# FEES
# ==========================================

FEE_BEARER_CUSTOMER = 'customer'   # the payer pays the fee on top of the amount
FEE_BEARER_MERCHANT = 'merchant'   # the receiver absorbs the fee (deducted from what they receive)
FEE_BEARER_PLATFORM = 'platform'   # the platform absorbs the fee; nobody is charged
FEE_BEARER_SPLIT = 'split'         # shared between payer and receiver

FEE_BEARERS = (
    (FEE_BEARER_CUSTOMER, _('Customer (payer)')),
    (FEE_BEARER_MERCHANT, _('Merchant (receiver)')),
    (FEE_BEARER_PLATFORM, _('Platform')),
    (FEE_BEARER_SPLIT, _('Split')),
)

FEE_TYPE_PERCENTAGE = 'percentage'
FEE_TYPE_FLAT = 'flat'
FEE_TYPE_HYBRID = 'hybrid'   # percentage + flat
FEE_TYPE_TIERED = 'tiered'   # fixed fee by amount band (see FeeTier)

FEE_TYPES = (
    (FEE_TYPE_PERCENTAGE, _('Percentage')),
    (FEE_TYPE_FLAT, _('Flat')),
    (FEE_TYPE_HYBRID, _('Hybrid (percentage + flat)')),
    (FEE_TYPE_TIERED, _('Tiered')),
)

# Channels used to pick deposit pricing
PAYMENT_CHANNEL_LOCAL_CARD = 'local_card'
PAYMENT_CHANNEL_INTL_CARD = 'intl_card'
PAYMENT_CHANNEL_DVA = 'dva'
PAYMENT_CHANNEL_BANK_TRANSFER = 'bank_transfer'
PAYMENT_CHANNEL_USSD = 'ussd'
PAYMENT_CHANNEL_QR = 'qr'
PAYMENT_CHANNEL_MOBILE_MONEY = 'mobile_money'
PAYMENT_CHANNEL_BANK = 'bank'

PAYMENT_CHANNELS = (
    (PAYMENT_CHANNEL_LOCAL_CARD, _('Local Card')),
    (PAYMENT_CHANNEL_INTL_CARD, _('International Card')),
    (PAYMENT_CHANNEL_DVA, _('Dedicated Virtual Account')),
    (PAYMENT_CHANNEL_BANK_TRANSFER, _('Bank Transfer')),
    (PAYMENT_CHANNEL_USSD, _('USSD')),
    (PAYMENT_CHANNEL_QR, _('QR Code')),
    (PAYMENT_CHANNEL_MOBILE_MONEY, _('Mobile Money')),
    (PAYMENT_CHANNEL_BANK, _('Pay with Bank')),
)

# ==========================================
# BANK ACCOUNTS & RECIPIENTS
# ==========================================

BANK_ACCOUNT_TYPE_SAVINGS = 'savings'
BANK_ACCOUNT_TYPE_CURRENT = 'current'

BANK_ACCOUNT_TYPES = (
    (BANK_ACCOUNT_TYPE_SAVINGS, _('Savings')),
    (BANK_ACCOUNT_TYPE_CURRENT, _('Current')),
)

RECIPIENT_TYPE_NUBAN = 'nuban'
RECIPIENT_TYPE_MOBILE_MONEY = 'mobile_money'
RECIPIENT_TYPE_GHIPSS = 'ghipss'
RECIPIENT_TYPE_BASA = 'basa'
RECIPIENT_TYPE_KEPSS = 'kepss'

RECIPIENT_TYPES = (
    (RECIPIENT_TYPE_NUBAN, _('NUBAN (Nigeria)')),
    (RECIPIENT_TYPE_MOBILE_MONEY, _('Mobile Money')),
    (RECIPIENT_TYPE_GHIPSS, _('GhIPSS (Ghana)')),
    (RECIPIENT_TYPE_BASA, _('BASA (South Africa)')),
    (RECIPIENT_TYPE_KEPSS, _('KEPSS (Kenya)')),
)

# ==========================================
# CARDS
# ==========================================

CARD_TYPE_MASTERCARD = 'mastercard'
CARD_TYPE_VISA = 'visa'
CARD_TYPE_VERVE = 'verve'
CARD_TYPE_DISCOVER = 'discover'
CARD_TYPE_AMEX = 'amex'
CARD_TYPE_OTHER = 'other'

CARD_TYPES = (
    (CARD_TYPE_MASTERCARD, _('Mastercard')),
    (CARD_TYPE_VISA, _('Visa')),
    (CARD_TYPE_VERVE, _('Verve')),
    (CARD_TYPE_DISCOVER, _('Discover')),
    (CARD_TYPE_AMEX, _('American Express')),
    (CARD_TYPE_OTHER, _('Other')),
)

# ==========================================
# PAYSTACK WEBHOOK EVENTS (complete list)
# ==========================================

WEBHOOK_EVENT_CHARGE_SUCCESS = 'charge.success'
WEBHOOK_EVENT_CHARGE_FAILED = 'charge.failed'
WEBHOOK_EVENT_CHARGE_DISPUTE_CREATE = 'charge.dispute.create'
WEBHOOK_EVENT_CHARGE_DISPUTE_REMIND = 'charge.dispute.remind'
WEBHOOK_EVENT_CHARGE_DISPUTE_RESOLVE = 'charge.dispute.resolve'
WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_SUCCESS = 'customeridentification.success'
WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_FAILED = 'customeridentification.failed'
WEBHOOK_EVENT_DVA_ASSIGN_SUCCESS = 'dedicatedaccount.assign.success'
WEBHOOK_EVENT_DVA_ASSIGN_FAILED = 'dedicatedaccount.assign.failed'
WEBHOOK_EVENT_INVOICE_CREATE = 'invoice.create'
WEBHOOK_EVENT_INVOICE_UPDATE = 'invoice.update'
WEBHOOK_EVENT_INVOICE_PAYMENT_FAILED = 'invoice.payment_failed'
WEBHOOK_EVENT_PAYMENT_REQUEST_PENDING = 'paymentrequest.pending'
WEBHOOK_EVENT_PAYMENT_REQUEST_SUCCESS = 'paymentrequest.success'
WEBHOOK_EVENT_REFUND_FAILED = 'refund.failed'
WEBHOOK_EVENT_REFUND_PENDING = 'refund.pending'
WEBHOOK_EVENT_REFUND_PROCESSED = 'refund.processed'
WEBHOOK_EVENT_REFUND_PROCESSING = 'refund.processing'
WEBHOOK_EVENT_SUBSCRIPTION_CREATE = 'subscription.create'
WEBHOOK_EVENT_SUBSCRIPTION_DISABLE = 'subscription.disable'
WEBHOOK_EVENT_SUBSCRIPTION_EXPIRING_CARDS = 'subscription.expiring_cards'
WEBHOOK_EVENT_SUBSCRIPTION_NOT_RENEW = 'subscription.not_renew'
WEBHOOK_EVENT_TRANSFER_SUCCESS = 'transfer.success'
WEBHOOK_EVENT_TRANSFER_FAILED = 'transfer.failed'
WEBHOOK_EVENT_TRANSFER_REVERSED = 'transfer.reversed'

WEBHOOK_EVENTS = (
    (WEBHOOK_EVENT_CHARGE_SUCCESS, _('Charge success')),
    (WEBHOOK_EVENT_CHARGE_FAILED, _('Charge failed')),
    (WEBHOOK_EVENT_CHARGE_DISPUTE_CREATE, _('Dispute created')),
    (WEBHOOK_EVENT_CHARGE_DISPUTE_REMIND, _('Dispute reminder')),
    (WEBHOOK_EVENT_CHARGE_DISPUTE_RESOLVE, _('Dispute resolved')),
    (WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_SUCCESS, _('Customer identification success')),
    (WEBHOOK_EVENT_CUSTOMER_IDENTIFICATION_FAILED, _('Customer identification failed')),
    (WEBHOOK_EVENT_DVA_ASSIGN_SUCCESS, _('Dedicated account assigned')),
    (WEBHOOK_EVENT_DVA_ASSIGN_FAILED, _('Dedicated account assignment failed')),
    (WEBHOOK_EVENT_INVOICE_CREATE, _('Invoice created')),
    (WEBHOOK_EVENT_INVOICE_UPDATE, _('Invoice updated')),
    (WEBHOOK_EVENT_INVOICE_PAYMENT_FAILED, _('Invoice payment failed')),
    (WEBHOOK_EVENT_PAYMENT_REQUEST_PENDING, _('Payment request pending')),
    (WEBHOOK_EVENT_PAYMENT_REQUEST_SUCCESS, _('Payment request paid')),
    (WEBHOOK_EVENT_REFUND_FAILED, _('Refund failed')),
    (WEBHOOK_EVENT_REFUND_PENDING, _('Refund pending')),
    (WEBHOOK_EVENT_REFUND_PROCESSED, _('Refund processed')),
    (WEBHOOK_EVENT_REFUND_PROCESSING, _('Refund processing')),
    (WEBHOOK_EVENT_SUBSCRIPTION_CREATE, _('Subscription created')),
    (WEBHOOK_EVENT_SUBSCRIPTION_DISABLE, _('Subscription disabled')),
    (WEBHOOK_EVENT_SUBSCRIPTION_EXPIRING_CARDS, _('Subscription cards expiring')),
    (WEBHOOK_EVENT_SUBSCRIPTION_NOT_RENEW, _('Subscription will not renew')),
    (WEBHOOK_EVENT_TRANSFER_SUCCESS, _('Transfer success')),
    (WEBHOOK_EVENT_TRANSFER_FAILED, _('Transfer failed')),
    (WEBHOOK_EVENT_TRANSFER_REVERSED, _('Transfer reversed')),
)

# ==========================================
# SETTLEMENTS
# ==========================================

SETTLEMENT_STATUS_PENDING = 'pending'
SETTLEMENT_STATUS_PROCESSING = 'processing'
SETTLEMENT_STATUS_SUCCESS = 'success'
SETTLEMENT_STATUS_FAILED = 'failed'

SETTLEMENT_STATUSES = (
    (SETTLEMENT_STATUS_PENDING, _('Pending')),
    (SETTLEMENT_STATUS_PROCESSING, _('Processing')),
    (SETTLEMENT_STATUS_SUCCESS, _('Success')),
    (SETTLEMENT_STATUS_FAILED, _('Failed')),
)

SETTLEMENT_SCHEDULE_MANUAL = 'manual'
SETTLEMENT_SCHEDULE_DAILY = 'daily'
SETTLEMENT_SCHEDULE_WEEKLY = 'weekly'
SETTLEMENT_SCHEDULE_MONTHLY = 'monthly'
SETTLEMENT_SCHEDULE_THRESHOLD = 'threshold'

SETTLEMENT_SCHEDULE_TYPES = (
    (SETTLEMENT_SCHEDULE_MANUAL, _('Manual')),
    (SETTLEMENT_SCHEDULE_DAILY, _('Daily')),
    (SETTLEMENT_SCHEDULE_WEEKLY, _('Weekly')),
    (SETTLEMENT_SCHEDULE_MONTHLY, _('Monthly')),
    (SETTLEMENT_SCHEDULE_THRESHOLD, _('Threshold')),
)

# ==========================================
# INTERNAL TRANSFER RECIPIENT LOOKUP
# ==========================================

LOOKUP_ID = 'id'
LOOKUP_TAG = 'tag'
LOOKUP_PHONE = 'phone_number'
LOOKUP_EMAIL = 'email'

RECIPIENT_LOOKUP_TYPES = (
    (LOOKUP_ID, _('Wallet ID')),
    (LOOKUP_TAG, _('Wallet tag')),
    (LOOKUP_PHONE, _('Phone number')),
    (LOOKUP_EMAIL, _('Email')),
)
