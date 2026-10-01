from django.db import models
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wallet.constants import (
    DIRECTION_CREDIT,
    DIRECTION_DEBIT,
    FEE_BEARERS,
    FINAL_TRANSACTION_STATUSES,
    PAYMENT_METHODS,
    TRANSACTION_DIRECTIONS,
    TRANSACTION_STATUS_CANCELLED,
    TRANSACTION_STATUS_FAILED,
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_PROCESSING,
    TRANSACTION_STATUS_REVERSED,
    TRANSACTION_STATUS_SUCCESS,
    TRANSACTION_STATUSES,
    TRANSACTION_TYPE_DEPOSIT,
    TRANSACTION_TYPE_PAYMENT,
    TRANSACTION_TYPE_TRANSFER,
    TRANSACTION_TYPES,
)
from wallet.models.base import BaseModel
from wallet.models.fields import WalletMoneyField


class TransactionQuerySet(models.QuerySet):
    def successful(self):
        return self.filter(status=TRANSACTION_STATUS_SUCCESS)

    def pending(self):
        return self.filter(status__in=[TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING])

    def failed(self):
        return self.filter(status=TRANSACTION_STATUS_FAILED)

    def cancelled(self):
        return self.filter(status=TRANSACTION_STATUS_CANCELLED)

    def credits(self):
        return self.filter(direction=DIRECTION_CREDIT)

    def debits(self):
        return self.filter(direction=DIRECTION_DEBIT)

    def by_type(self, transaction_type):
        return self.filter(transaction_type=transaction_type)

    def by_wallet(self, wallet):
        return self.filter(wallet=wallet)

    def with_wallet_details(self):
        return self.select_related('wallet', 'wallet__user')

    def with_full_details(self):
        return self.select_related(
            'wallet', 'wallet__user', 'counterparty_wallet', 'counterparty_wallet__user',
            'recipient_bank_account', 'recipient_bank_account__bank', 'card', 'related_transaction',
        )

    def recent(self, days=30):
        return self.filter(created_at__gte=timezone.now() - timezone.timedelta(days=days))

    def in_date_range(self, start_date=None, end_date=None):
        queryset = self
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        return queryset

    def by_amount_range(self, min_amount=None, max_amount=None):
        queryset = self
        if min_amount is not None:
            queryset = queryset.filter(amount__gte=min_amount)
        if max_amount is not None:
            queryset = queryset.filter(amount__lte=max_amount)
        return queryset

    def with_statistics(self):
        return self.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            average_amount=Avg('amount'),
            min_amount=Min('amount'),
            max_amount=Max('amount'),
            total_fees=Sum('fees'),
        )

    def statistics(self):
        success = Q(status=TRANSACTION_STATUS_SUCCESS)
        return self.aggregate(
            total_count=Count('id'),
            successful_count=Count('id', filter=success),
            pending_count=Count('id', filter=Q(status__in=[TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING])),
            failed_count=Count('id', filter=Q(status=TRANSACTION_STATUS_FAILED)),
            total_credits=Sum('total_amount', filter=success & Q(direction=DIRECTION_CREDIT)),
            total_debits=Sum('total_amount', filter=success & Q(direction=DIRECTION_DEBIT)),
            total_fees=Sum('fees', filter=success),
            average_amount=Avg('amount', filter=success),
        )


class TransactionManager(models.Manager.from_queryset(TransactionQuerySet)):
    def for_wallet(self, wallet):
        return self.get_queryset().by_wallet(wallet)

    def statistics(self, wallet=None, start_date=None, end_date=None):
        queryset = self.get_queryset()
        if wallet:
            queryset = queryset.by_wallet(wallet)
        return queryset.in_date_range(start_date, end_date).statistics()


class Transaction(BaseModel):
    """
    One balance movement on one wallet (a ledger entry).

    * ``amount`` - the face value of the operation (what was requested).
    * ``fees`` - the fee attached to the operation.
    * ``total_amount`` - what actually moved on *this* wallet's balance.
    * ``direction`` - credit or debit on this wallet.
    * ``balance_after`` - this wallet's balance right after the posting.

    Internal transfers and wallet payments produce two linked rows - a debit on
    the sender and a credit on the receiver - so every wallet has a complete
    statement of its own.
    """

    wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.PROTECT, related_name='transactions', verbose_name=_('Wallet'),
    )
    amount = WalletMoneyField(verbose_name=_('Amount'))
    fees = WalletMoneyField(default=0, verbose_name=_('Fees'))
    total_amount = WalletMoneyField(
        default=0, verbose_name=_('Total amount'), help_text=_("Amount that moved on this wallet's balance"),
    )
    balance_after = WalletMoneyField(null=True, blank=True, verbose_name=_('Balance after'))
    ledger_sequence = models.PositiveBigIntegerField(
        null=True, blank=True, editable=False, verbose_name=_('Ledger sequence'),
        help_text=_("Position in the wallet's ledger (set when the entry changes the balance)"),
    )
    fee_bearer = models.CharField(
        max_length=20, choices=FEE_BEARERS, blank=True, null=True, verbose_name=_('Fee bearer'),
    )

    reference = models.CharField(max_length=100, unique=True, verbose_name=_('Reference'))
    transaction_type = models.CharField(
        max_length=20, choices=TRANSACTION_TYPES, default=TRANSACTION_TYPE_DEPOSIT, db_index=True,
        verbose_name=_('Transaction type'),
    )
    direction = models.CharField(
        max_length=10, choices=TRANSACTION_DIRECTIONS, default=DIRECTION_CREDIT, db_index=True,
        verbose_name=_('Direction'),
    )
    status = models.CharField(
        max_length=20, choices=TRANSACTION_STATUSES, default=TRANSACTION_STATUS_PENDING, db_index=True,
        verbose_name=_('Status'),
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, blank=True, null=True, verbose_name=_('Payment method'),
    )
    channel = models.CharField(
        max_length=50, blank=True, default='', verbose_name=_('Channel'), help_text=_('Raw Paystack channel'),
    )
    description = models.TextField(blank=True, default='', verbose_name=_('Description'))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_('Metadata'))

    # Paystack references
    paystack_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    paystack_transfer_code = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    paystack_id = models.BigIntegerField(blank=True, null=True, help_text=_('Paystack transaction/transfer/refund id'))
    paystack_response = models.JSONField(blank=True, null=True)

    # Relationships
    counterparty_wallet = models.ForeignKey(
        'wallet.Wallet', on_delete=models.SET_NULL, related_name='counterparty_transactions',
        blank=True, null=True, verbose_name=_('Counterparty wallet'),
        help_text=_('The other wallet in a transfer or payment'),
    )
    recipient_bank_account = models.ForeignKey(
        'wallet.BankAccount', on_delete=models.SET_NULL, related_name='transactions',
        blank=True, null=True, verbose_name=_('Recipient bank account'),
    )
    card = models.ForeignKey(
        'wallet.Card', on_delete=models.SET_NULL, related_name='transactions',
        blank=True, null=True, verbose_name=_('Card'),
    )
    related_transaction = models.ForeignKey(
        'self', on_delete=models.SET_NULL, related_name='related_transactions',
        blank=True, null=True, verbose_name=_('Related transaction'),
        help_text=_('The other leg of a transfer, or the original of a refund/reversal'),
    )

    # Audit
    ip_address = models.GenericIPAddressField(blank=True, null=True, verbose_name=_('IP address'))
    user_agent = models.TextField(blank=True, default='', verbose_name=_('User agent'))
    completed_at = models.DateTimeField(blank=True, null=True, db_index=True, verbose_name=_('Completed at'))
    failed_reason = models.TextField(blank=True, default='', verbose_name=_('Failed reason'))

    objects = TransactionManager()

    class Meta:
        verbose_name = _('Transaction')
        verbose_name_plural = _('Transactions')
        ordering = ['-created_at', '-ledger_sequence']
        indexes = [
            models.Index(fields=['wallet', 'created_at'], name='txn_wallet_created_idx'),
            models.Index(fields=['wallet', 'status'], name='txn_wallet_status_idx'),
            models.Index(fields=['transaction_type', 'status'], name='txn_type_status_idx'),
            models.Index(fields=['status', 'created_at'], name='txn_status_created_idx'),
            models.Index(fields=['wallet', 'ledger_sequence'], name='txn_wallet_ledger_idx'),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} ({self.get_status_display()})"

    def __repr__(self):
        return (
            f"<Transaction id={self.id} type={self.transaction_type} direction={self.direction} "
            f"status={self.status} amount={self.amount} reference={self.reference}>"
        )

    def save(self, *args, **kwargs):
        if not self.reference:
            from wallet.utils.id_generators import generate_transaction_reference
            self.reference = generate_transaction_reference()
        if self.balance_after is not None and self.ledger_sequence is None and self.wallet_id:
            # Posted entries are saved right after Wallet.credit()/debit() bumped the wallet's
            # sequence inside the same locked DB transaction, so this is this entry's position.
            from wallet.models.wallet import Wallet
            self.ledger_sequence = Wallet.objects.filter(pk=self.wallet_id).values_list(
                'ledger_sequence', flat=True).first()
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = {*update_fields, 'ledger_sequence'}
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_completed(self):
        return self.status in FINAL_TRANSACTION_STATUSES

    @property
    def is_final(self):
        return self.status in FINAL_TRANSACTION_STATUSES

    @property
    def is_successful(self):
        return self.status == TRANSACTION_STATUS_SUCCESS

    @property
    def is_failed(self):
        return self.status == TRANSACTION_STATUS_FAILED

    @property
    def is_pending(self):
        return self.status in (TRANSACTION_STATUS_PENDING, TRANSACTION_STATUS_PROCESSING)

    @property
    def is_cancelled(self):
        return self.status == TRANSACTION_STATUS_CANCELLED

    @property
    def is_reversed(self):
        return self.status == TRANSACTION_STATUS_REVERSED

    @property
    def is_credit(self):
        return self.direction == DIRECTION_CREDIT

    @property
    def is_debit(self):
        return self.direction == DIRECTION_DEBIT

    @property
    def has_fees(self):
        return self.fees.amount > 0

    @property
    def net_amount(self):
        """Amount after fees (kept for backwards compatibility)."""
        return self.amount - self.fees

    @property
    def requires_otp(self):
        return bool((self.metadata or {}).get('requires_otp')) and self.is_pending

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def can_be_refunded(self):
        """Card/bank deposits can be refunded to the payer through Paystack."""
        return (
            self.is_successful
            and self.transaction_type == TRANSACTION_TYPE_DEPOSIT
            and bool(self.paystack_reference)
        )

    def can_be_cancelled(self):
        """Only deposits not yet paid and escrowed payments not yet released can be cancelled."""
        if not self.is_pending:
            return False
        if self.transaction_type == TRANSACTION_TYPE_DEPOSIT:
            return True
        return self.transaction_type == TRANSACTION_TYPE_PAYMENT and self.is_debit and bool(
            (self.metadata or {}).get('escrow')
        )

    def can_be_reversed(self):
        """Internal movements (transfers, payments) can be reversed by staff."""
        return (
            self.is_successful
            and self.is_debit
            and self.transaction_type in (TRANSACTION_TYPE_TRANSFER, TRANSACTION_TYPE_PAYMENT)
        )

    def validate_amount(self):
        if self.amount.amount <= 0:
            raise ValueError(_("Transaction amount must be greater than zero"))
        return True
