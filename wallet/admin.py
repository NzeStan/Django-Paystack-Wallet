"""
Django admin for the wallet.

Balances and ledger entries are read-only here on purpose: editing money by
hand silently corrupts the books. Use the actions (which go through the
services) - or ``WalletService().credit_wallet(...)`` for manual adjustments.
"""
from django.contrib import admin, messages
from django.db.models import Sum
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from wallet.exceptions import WalletError
from wallet.models import (
    Bank,
    BankAccount,
    Card,
    FeeConfiguration,
    FeeHistory,
    FeeTier,
    Settlement,
    SettlementSchedule,
    Transaction,
    Wallet,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
    WebhookEvent,
)
from wallet.utils.exporters import export_queryset_to_csv


def _link(obj, label=None):
    if obj is None:
        return '-'
    url = reverse(f'admin:{obj._meta.app_label}_{obj._meta.model_name}_change', args=[obj.pk])
    return format_html('<a href="{}">{}</a>', url, label or str(obj))


def _run(modeladmin, request, queryset, func, success_message):
    done = 0
    for obj in queryset:
        try:
            func(obj)
            done += 1
        except WalletError as exc:
            modeladmin.message_user(request, f"{obj}: {exc.message}", messages.ERROR)
        except Exception as exc:  # admin actions should report, not crash
            modeladmin.message_user(request, f"{obj}: {exc}", messages.ERROR)
    if done:
        modeladmin.message_user(request, success_message.format(count=done), messages.SUCCESS)


class CSVExportMixin:
    export_fields = ()

    @admin.action(description=_("Export selected to CSV"))
    def export_csv(self, request, queryset):
        fields = self.export_fields or [f.name for f in self.model._meta.fields]
        return export_queryset_to_csv(queryset, fields, self.model._meta.model_name)


class ReadOnlyMoneyMixin:
    def has_delete_permission(self, request, obj=None):
        return False


class TransactionInline(admin.TabularInline):
    model = Transaction
    fk_name = 'wallet'
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True
    fields = ('reference', 'transaction_type', 'direction', 'status', 'amount', 'total_amount', 'created_at')
    readonly_fields = fields
    ordering = ('-created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('-created_at')


@admin.register(Wallet)
class WalletAdmin(CSVExportMixin, ReadOnlyMoneyMixin, admin.ModelAdmin):
    list_display = ('__str__', 'tag', 'phone_number', 'balance', 'is_active', 'is_locked', 'dedicated_account_number',
                    'created_at')
    list_filter = ('is_active', 'is_locked', 'dedicated_account_active', 'customer_identified')
    search_fields = ('tag', 'phone_number', 'user__email', 'paystack_customer_code', 'dedicated_account_number')
    readonly_fields = (
        'id', 'user', 'balance', 'last_transaction_date', 'paystack_customer_code', 'paystack_customer_id',
        'customer_identified', 'dedicated_account_id', 'dedicated_account_number', 'dedicated_account_name',
        'dedicated_account_bank', 'dedicated_account_bank_slug', 'dedicated_account_active', 'has_pin',
        'created_at', 'updated_at',
    )
    fields = ('id', 'user', 'balance', 'tag', 'phone_number', 'is_active', 'is_locked', 'locked_reason',
              'daily_limit', 'has_pin', 'last_transaction_date', 'paystack_customer_code', 'paystack_customer_id',
              'customer_identified', 'dedicated_account_number', 'dedicated_account_name', 'dedicated_account_bank',
              'dedicated_account_active', 'metadata', 'created_at', 'updated_at')
    list_select_related = ('user',)
    inlines = [TransactionInline]
    actions = ['lock_wallets', 'unlock_wallets', 'create_paystack_customers', 'create_dedicated_accounts',
               'reset_pins', 'export_csv']
    export_fields = ('id', 'user.email', 'tag', 'phone_number', 'balance', 'is_active', 'is_locked', 'created_at')

    def has_add_permission(self, request):
        return False

    @admin.display(boolean=True, description=_('PIN set'))
    def has_pin(self, obj):
        return obj.has_pin

    @admin.action(description=_("Lock selected wallets"))
    def lock_wallets(self, request, queryset):
        from wallet.services.wallet_service import WalletService
        service = WalletService()
        _run(self, request, queryset, lambda w: service.lock_wallet_account(w, 'Locked by admin', request.user),
             "Locked {count} wallet(s)")

    @admin.action(description=_("Unlock selected wallets"))
    def unlock_wallets(self, request, queryset):
        from wallet.services.wallet_service import WalletService
        service = WalletService()
        _run(self, request, queryset, lambda w: service.unlock_wallet_account(w, request.user), "Unlocked {count} wallet(s)")

    @admin.action(description=_("Create Paystack customers"))
    def create_paystack_customers(self, request, queryset):
        from wallet.services.wallet_service import WalletService
        service = WalletService()
        _run(self, request, queryset, service.ensure_customer, "Created/linked {count} customer(s)")

    @admin.action(description=_("Create dedicated virtual accounts"))
    def create_dedicated_accounts(self, request, queryset):
        from wallet.services.wallet_service import WalletService
        service = WalletService()
        _run(self, request, queryset, service.create_dedicated_account, "Created {count} dedicated account(s)")

    @admin.action(description=_("Reset transaction PINs"))
    def reset_pins(self, request, queryset):
        _run(self, request, queryset, lambda w: w.clear_pin(), "Reset {count} PIN(s)")


@admin.register(Transaction)
class TransactionAdmin(CSVExportMixin, ReadOnlyMoneyMixin, admin.ModelAdmin):
    list_display = ('reference', 'wallet_link', 'transaction_type', 'direction', 'status', 'amount', 'fees',
                    'total_amount', 'payment_method', 'created_at')
    list_filter = ('transaction_type', 'direction', 'status', 'payment_method', 'fee_bearer', 'created_at')
    search_fields = ('reference', 'paystack_reference', 'paystack_transfer_code', 'wallet__user__email',
                     'wallet__tag', 'description')
    date_hierarchy = 'created_at'
    list_select_related = ('wallet', 'wallet__user')
    actions = ['verify_with_paystack', 'refund_to_card', 'reverse', 'export_csv']
    export_fields = ('reference', 'wallet.user.email', 'transaction_type', 'direction', 'status', 'amount', 'fees',
                     'total_amount', 'balance_after', 'payment_method', 'description', 'created_at')

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.display(description=_('Wallet'))
    def wallet_link(self, obj):
        return _link(obj.wallet, obj.wallet.tag or obj.wallet_id)

    @admin.action(description=_("Verify with Paystack (deposits & withdrawals)"))
    def verify_with_paystack(self, request, queryset):
        from wallet.services.wallet_service import WalletService
        service = WalletService()

        def verify(txn):
            if txn.transaction_type == 'deposit':
                service.verify_deposit(txn.reference)
            elif txn.transaction_type == 'withdrawal':
                service.verify_withdrawal(txn)
        _run(self, request, queryset.filter(transaction_type__in=['deposit', 'withdrawal']), verify,
             "Verified {count} transaction(s)")

    @admin.action(description=_("Refund deposit to card/bank (full)"))
    def refund_to_card(self, request, queryset):
        from wallet.services.transaction_service import TransactionService
        service = TransactionService()
        _run(self, request, queryset, lambda t: service.refund_deposit(t, reason='Refunded by admin', performed_by=request.user),
             "Started {count} refund(s)")

    @admin.action(description=_("Reverse transfer/payment"))
    def reverse(self, request, queryset):
        from wallet.services.transaction_service import TransactionService
        service = TransactionService()
        _run(self, request, queryset, lambda t: service.reverse_transaction(t, reason='Reversed by admin', performed_by=request.user),
             "Reversed {count} transaction(s)")

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            queryset = response.context_data['cl'].queryset
            response.context_data['summary'] = queryset.filter(status='success').aggregate(
                total=Sum('total_amount'), fees=Sum('fees'))
        except (AttributeError, KeyError):
            pass
        return response


@admin.register(Card)
class CardAdmin(CSVExportMixin, admin.ModelAdmin):
    list_display = ('__str__', 'wallet', 'expiry', 'bank', 'country_code', 'is_default', 'is_active', 'created_at')
    list_filter = ('card_type', 'is_active', 'is_default', 'country_code')
    search_fields = ('last_four', 'bin', 'wallet__user__email', 'card_holder_name')
    readonly_fields = ('paystack_authorization_code', 'paystack_authorization_signature', 'paystack_card_data',
                       'created_at', 'updated_at')
    list_select_related = ('wallet', 'wallet__user')


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'currency', 'country', 'type', 'pay_with_bank', 'is_active')
    list_filter = ('currency', 'country', 'type', 'is_active')
    search_fields = ('name', 'code', 'slug')
    actions = ['sync_from_paystack']

    @admin.action(description=_("Sync all banks from Paystack"))
    def sync_from_paystack(self, request, queryset):
        from wallet.services.bank_account_service import BankAccountService
        try:
            created, updated, errors = BankAccountService().sync_banks()
            self.message_user(request, f"Created {created}, updated {updated}, errors {errors}")
        except WalletError as exc:
            self.message_user(request, exc.message, messages.ERROR)


@admin.register(BankAccount)
class BankAccountAdmin(CSVExportMixin, admin.ModelAdmin):
    list_display = ('account_name', 'masked_account_number', 'bank', 'wallet', 'is_verified', 'is_default',
                    'is_active', 'has_recipient')
    list_filter = ('is_verified', 'is_active', 'bank__currency')
    search_fields = ('account_name', 'account_number', 'wallet__user__email', 'paystack_recipient_code')
    readonly_fields = ('paystack_recipient_code', 'paystack_recipient_id', 'paystack_data', 'created_at',
                       'updated_at')
    list_select_related = ('wallet', 'bank')
    actions = ['create_recipient_codes', 'export_csv']

    @admin.display(boolean=True, description=_('Recipient'))
    def has_recipient(self, obj):
        return bool(obj.paystack_recipient_code)

    @admin.action(description=_("Create missing Paystack transfer recipients"))
    def create_recipient_codes(self, request, queryset):
        from wallet.services.bank_account_service import BankAccountService
        service = BankAccountService()
        _run(self, request, queryset, service.ensure_recipient, "Ensured {count} recipient(s)")


@admin.register(Settlement)
class SettlementAdmin(CSVExportMixin, ReadOnlyMoneyMixin, admin.ModelAdmin):
    list_display = ('reference', 'wallet', 'amount', 'fees', 'status', 'bank_account', 'created_at', 'settled_at')
    list_filter = ('status', 'created_at')
    search_fields = ('reference', 'paystack_transfer_code', 'wallet__user__email')
    list_select_related = ('wallet', 'bank_account', 'bank_account__bank')
    actions = ['verify_with_paystack', 'retry', 'export_csv']

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Verify with Paystack"))
    def verify_with_paystack(self, request, queryset):
        from wallet.services.settlement_service import SettlementService
        service = SettlementService()
        _run(self, request, queryset.exclude(transaction=None), service.verify_settlement,
             "Verified {count} settlement(s)")

    @admin.action(description=_("Retry failed settlements"))
    def retry(self, request, queryset):
        from wallet.services.settlement_service import SettlementService
        service = SettlementService()
        _run(self, request, queryset.filter(status='failed'), service.retry_settlement,
             "Retried {count} settlement(s)")


@admin.register(SettlementSchedule)
class SettlementScheduleAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'schedule_type', 'bank_account', 'is_active', 'last_settlement', 'next_settlement')
    list_filter = ('schedule_type', 'is_active')
    search_fields = ('wallet__user__email', 'wallet__tag')
    readonly_fields = ('last_settlement', 'next_settlement', 'created_at', 'updated_at')
    list_select_related = ('wallet', 'bank_account')
    actions = ['recalculate_next_settlement']

    @admin.action(description=_("Recalculate next settlement"))
    def recalculate_next_settlement(self, request, queryset):
        _run(self, request, queryset, lambda s: s.calculate_next_settlement(), "Updated {count} schedule(s)")


class FeeTierInline(admin.TabularInline):
    model = FeeTier
    extra = 1


@admin.register(FeeConfiguration)
class FeeConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'scope', 'transaction_type', 'payment_channel', 'fee_type', 'percentage_fee', 'flat_fee',
                    'fee_cap', 'fee_bearer', 'priority', 'is_active')
    list_filter = ('transaction_type', 'payment_channel', 'fee_type', 'fee_bearer', 'is_active')
    search_fields = ('name', 'description', 'wallet__user__email')
    list_editable = ('priority', 'is_active')
    autocomplete_fields = ('wallet',)
    inlines = [FeeTierInline]
    fieldsets = (
        (None, {'fields': ('name', 'description', 'wallet', 'transaction_type', 'payment_channel', 'is_active',
                           'priority')}),
        (_('Pricing'), {'fields': ('fee_type', 'percentage_fee', 'flat_fee', 'minimum_fee', 'fee_cap',
                                   'waiver_threshold')}),
        (_('Who pays'), {'fields': ('fee_bearer', 'customer_percentage', 'merchant_percentage')}),
        (_('Validity'), {'fields': ('valid_from', 'valid_until', 'metadata')}),
    )

    @admin.display(description=_('Scope'))
    def scope(self, obj):
        return obj.wallet or _('Global')


@admin.register(FeeHistory)
class FeeHistoryAdmin(ReadOnlyMoneyMixin, admin.ModelAdmin):
    list_display = ('transaction', 'calculated_fee', 'original_amount', 'fee_bearer', 'calculation_method',
                    'created_at')
    list_filter = ('calculation_method', 'fee_bearer')
    search_fields = ('transaction__reference',)
    list_select_related = ('transaction',)

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'reference', 'processed', 'processing_attempts', 'transaction', 'created_at')
    list_filter = ('event_type', 'processed')
    search_fields = ('reference', 'idempotency_key', 'event_type')
    date_hierarchy = 'created_at'
    actions = ['reprocess']

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Reprocess selected events"))
    def reprocess(self, request, queryset):
        from wallet.services.webhook_service import WebhookService
        service = WebhookService()
        _run(self, request, queryset, service.process_event, "Reprocessed {count} event(s)")


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'is_active', 'retry_count', 'timeout')
    list_filter = ('is_active',)
    search_fields = ('name', 'url')
    filter_horizontal = ('wallets',)


@admin.register(WebhookDeliveryAttempt)
class WebhookDeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ('webhook_endpoint', 'webhook_event', 'attempt_number', 'response_code', 'is_success',
                    'created_at')
    list_filter = ('is_success', 'webhook_endpoint')
    actions = ['retry']

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Retry failed deliveries"))
    def retry(self, request, queryset):
        from wallet.services.webhook_service import WebhookService
        service = WebhookService()
        _run(self, request, queryset.filter(is_success=False), service.retry_failed_webhook_delivery,
             "Retried {count} deliveries")
