from django.contrib import admin
from django.urls import path
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.db.models import Sum, Count, Avg, Max, Min
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages
from django import forms
from django.utils import timezone
from wallet.models import (
    Wallet, Transaction, Card, Bank, BankAccount, 
    WebhookEvent, WebhookEndpoint, WebhookDeliveryAttempt,
    TransferRecipient, Settlement, SettlementSchedule
)
from wallet.models.fee_config import FeeConfiguration, FeeTier, FeeHistory
from wallet.services.wallet_service import WalletService
from wallet.services.transaction_service import TransactionService
from wallet.services.settlement_service import SettlementService
from wallet.utils.exporters import (
    export_queryset_to_csv, export_queryset_to_excel, export_queryset_to_pdf
)
from django.urls import reverse

import logging
logger = logging.getLogger(__name__)


class ExportMixin:
    """Mixin to add export actions to admin"""
    
    actions = ['export_to_csv', 'export_to_excel', 'export_to_pdf']
    
    def export_to_csv(self, request, queryset):
        """Export selected items to CSV"""
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]
        
        response = export_queryset_to_csv(
            queryset=queryset,
            fields=field_names,
            filename_prefix=meta.verbose_name_plural.lower().replace(' ', '_')
        )
        
        return response
    export_to_csv.short_description = _("Export selected items to CSV")
    
    def export_to_excel(self, request, queryset):
        """Export selected items to Excel"""
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]
        
        response = export_queryset_to_excel(
            queryset=queryset,
            fields=field_names,
            filename_prefix=meta.verbose_name_plural.lower().replace(' ', '_'),
            sheet_name=meta.verbose_name_plural[:31]
        )
        
        return response
    export_to_excel.short_description = _("Export selected items to Excel")
    
    def export_to_pdf(self, request, queryset):
        """Export selected items to PDF"""
        meta = self.model._meta
        field_names = [field.name for field in meta.fields if not field.name.endswith('_data')]
        
        title = _("{} Export").format(meta.verbose_name_plural)
        
        response = export_queryset_to_pdf(
            queryset=queryset,
            fields=field_names,
            filename_prefix=meta.verbose_name_plural.lower().replace(' ', '_'),
            title=title
        )
        
        return response
    export_to_pdf.short_description = _("Export selected items to PDF")


class AnalyticsMixin:
    """Mixin to add analytics to admin"""
    
    def get_urls(self):
        """Add custom URLs for analytics"""
        urls = super().get_urls()
        custom_urls = [
            path('analytics/', self.admin_site.admin_view(self.analytics_view),
                 name=f'{self.model._meta.app_label}_{self.model._meta.model_name}_analytics'),
        ]
        return custom_urls + urls
    
    def analytics_view(self, request):
        """View for displaying analytics"""
        # This should be implemented by the subclass
        raise NotImplementedError("Subclasses must implement analytics_view")


class WalletAdmin(ExportMixin, AnalyticsMixin, admin.ModelAdmin):
    """Admin for the Wallet model"""
    
    list_display = (
        'id', 'user', 'tag', 'formatted_balance', 'is_active', 
        'is_locked', 'last_transaction_date', 'created_at'
    )
    list_filter = ('is_active', 'is_locked', 'created_at')
    search_fields = ('id', 'user__email', 'user__username', 'tag', 'dedicated_account_number')
    readonly_fields = (
        'id', 'user', 'balance', 'last_transaction_date',
        'daily_transaction_total', 'daily_transaction_count',
        'daily_transaction_reset', 'paystack_customer_code',
        'dedicated_account_number', 'dedicated_account_bank',
        'created_at', 'updated_at'
    )
    actions = ExportMixin.actions + ['lock_wallets', 'unlock_wallets', 'create_dedicated_accounts']
    fieldsets = (
        (None, {
            'fields': ('id', 'user', 'tag', 'balance')
        }),
        (_('Status'), {
            'fields': ('is_active', 'is_locked')
        }),
        (_('Transaction Metrics'), {
            'fields': (
                'last_transaction_date', 'daily_transaction_total',
                'daily_transaction_count', 'daily_transaction_reset'
            )
        }),
        (_('Paystack Integration'), {
            'fields': (
                'paystack_customer_code', 'dedicated_account_number',
                'dedicated_account_bank'
            )
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def formatted_balance(self, obj):
        """Format balance for display"""
        return f"{obj.balance.amount} {obj.balance.currency.code}"
    formatted_balance.short_description = _("Balance")
    
    def lock_wallets(self, request, queryset):
        """Lock selected wallets"""
        for wallet in queryset:
            wallet.lock()
        messages.success(request, _("{} wallets locked successfully").format(queryset.count()))
    lock_wallets.short_description = _("Lock selected wallets")
    
    def unlock_wallets(self, request, queryset):
        """Unlock selected wallets"""
        for wallet in queryset:
            wallet.unlock()
        messages.success(request, _("{} wallets unlocked successfully").format(queryset.count()))
    unlock_wallets.short_description = _("Unlock selected wallets")
    
    def create_dedicated_accounts(self, request, queryset):
        """Create dedicated accounts for selected wallets"""
        wallet_service = WalletService()
        count = 0
        
        for wallet in queryset:
            if not wallet.dedicated_account_number:
                success = wallet_service.create_dedicated_account(wallet)
                if success:
                    count += 1
        
        if count:
            messages.success(request, _("Created {} dedicated accounts successfully").format(count))
        else:
            messages.info(request, _("No new dedicated accounts were created"))
    create_dedicated_accounts.short_description = _("Create dedicated accounts for selected wallets")
    
    def analytics_view(self, request):
        """Analytics view for wallets"""
        from django.db.models import Sum, Count, Q, F, DecimalField
        from django.db.models.functions import Cast, TruncDate
        
        # Get aggregate metrics
        total_wallets = Wallet.objects.count()
        active_wallets = Wallet.objects.filter(is_active=True, is_locked=False).count()
        locked_wallets = Wallet.objects.filter(is_locked=True).count()
        inactive_wallets = Wallet.objects.filter(is_active=False).count()
        
        # Get balance metrics
        total_balance = Wallet.objects.aggregate(
            total=Sum(Cast(F('balance'), output_field=DecimalField()))
        )['total'] or 0
        
        # Get wallet creation trend
        wallets_by_date = (
            Wallet.objects
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        
        context = {
            'title': _("Wallet Analytics"),
            'total_wallets': total_wallets,
            'active_wallets': active_wallets,
            'locked_wallets': locked_wallets,
            'inactive_wallets': inactive_wallets,
            'total_balance': total_balance,
            'wallets_by_date': wallets_by_date,
            'opts': self.model._meta,
        }
        
        return render(request, 'admin/wallet/analytics/wallet_analytics.html', context)


class TransactionAdmin(ExportMixin, AnalyticsMixin, admin.ModelAdmin):
    """Admin for the Transaction model"""
    list_display = (
        'id',
        'reference',
        'wallet_link',
        'formatted_amount',
        'fees_display',
        'fee_bearer_display',
        'net_amount_display',
        'transaction_type',
        'status',
        'created_at',
        'completed_at',
    )
    list_filter = (
        'transaction_type',
        'status',
        'payment_method',
        'fee_bearer',
        'created_at',
        'completed_at',
    )
    search_fields = (
        'id', 'wallet__id', 'wallet__user__email', 'reference',
        'paystack_reference', 'description'
    )
    readonly_fields = (
        'id',
        'wallet',
        'reference',
        'amount',
        'fees',
        'fee_bearer',
        'net_amount_display',
        'transaction_type',
        'status',
        'payment_method',
        'description',
        'metadata',
        'paystack_reference',
        'paystack_response',
        'recipient_wallet',
        'recipient_bank_account',
        'card',
        'related_transaction',
        'ip_address',
        'user_agent',
        'completed_at',
        'failed_reason',
        'created_at',
        'updated_at',
    )
    actions = ExportMixin.actions + ['mark_as_successful', 'mark_as_failed', 'refresh_from_paystack']
    fieldsets = (
        (None, {
            'fields': ('id', 'reference', 'wallet')
        }),
        (_('Amount Details'), {
            'fields': (
                'amount',
                'fees',
                'fee_bearer',
                'net_amount_display',
            )
        }),
        (_('Transaction Details'), {
            'fields': (
                'transaction_type',
                'status',
                'payment_method',
                'description',
                'metadata',
            )
        }),
        (_('Related Entities'), {
            'fields': (
                'recipient_wallet',
                'recipient_bank_account',
                'card',
                'related_transaction',
            )
        }),
        (_('Paystack Integration'), {
            'fields': (
                'paystack_reference',
                'paystack_response',
            )
        }),
        (_('Additional Information'), {
            'fields': (
                'ip_address',
                'user_agent',
                'completed_at',
                'failed_reason',
            )
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at')
        }),
    )

    
    def wallet_link(self, obj):
        """Link to the wallet admin"""
        
        url = reverse('admin:wallet_wallet_change', args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet)
    wallet_link.short_description = _("Wallet")
    
    def formatted_amount(self, obj):
        """Format amount for display"""
        return f"{obj.amount.amount} {obj.amount.currency.code}"
    formatted_amount.short_description = _("Amount")
    
    def mark_as_successful(self, request, queryset):
        """Mark selected transactions as successful"""
        transaction_service = TransactionService()
        
        for transaction in queryset.filter(status='pending'):
            try:
                transaction_service.mark_transaction_as_success(transaction)
            except Exception as e:
                messages.error(request, _(
                    "Error marking transaction {} as successful: {}").format(
                        transaction.reference, str(e)
                    )
                )
        
        messages.success(request, _("Transactions marked as successful"))
    mark_as_successful.short_description = _("Mark selected transactions as successful")
    
    def mark_as_failed(self, request, queryset):
        """Mark selected transactions as failed"""
        transaction_service = TransactionService()
        
        for transaction in queryset.filter(status='pending'):
            try:
                transaction_service.mark_transaction_as_failed(transaction, _("Marked as failed by admin"))
            except Exception as e:
                messages.error(request, _(
                    "Error marking transaction {} as failed: {}").format(
                        transaction.reference, str(e)
                    )
                )
        
        messages.success(request, _("Transactions marked as failed"))
    mark_as_failed.short_description = _("Mark selected transactions as failed")
    
    def refresh_from_paystack(self, request, queryset):
        """Verify transaction status with Paystack"""
        transaction_service = TransactionService()
        updated = 0
        
        for transaction in queryset:
            if not transaction.paystack_reference:
                continue
                
            try:
                paystack_data = transaction_service.verify_paystack_transaction(transaction.paystack_reference)
                
                # Update transaction based on Paystack status
                if paystack_data['status'] == 'success':
                    transaction_service.mark_transaction_as_success(transaction, paystack_data)
                elif paystack_data['status'] in ['failed', 'abandoned']:
                    transaction_service.mark_transaction_as_failed(transaction, paystack_data.get('gateway_response'), paystack_data)
                
                updated += 1
            except Exception as e:
                messages.error(request, _(
                    "Error refreshing transaction {}: {}").format(
                        transaction.reference, str(e)
                    )
                )
        
        if updated:
            messages.success(request, _("Updated {} transactions from Paystack").format(updated))
        else:
            messages.info(request, _("No transactions were updated"))
    refresh_from_paystack.short_description = _("Refresh status from Paystack")

    def fees_display(self, obj):
        """Display fee amount"""
        if obj.fees and obj.fees.amount > 0:
            return f"{obj.fees.amount} {obj.fees.currency.code}"
        return "-"
    fees_display.short_description = _("Fees")
    
    def fee_bearer_display(self, obj):
        """Display fee bearer with color coding"""
        if not obj.fee_bearer:
            return "-"
        
        colors = {
            'customer': '#28a745',  # Green
            'merchant': '#ffc107',  # Yellow
            'platform': '#dc3545',  # Red
            'split': '#17a2b8',  # Blue
        }
        
        color = colors.get(obj.fee_bearer, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_fee_bearer_display() if obj.fee_bearer else '-'
        )
    fee_bearer_display.short_description = _("Fee Bearer")
    
    def net_amount_display(self, obj):
        """Display net amount (amount - fees)"""
        net = obj.net_amount
        return f"{net.amount} {net.currency.code}"
    net_amount_display.short_description = _("Net Amount")

    def get_queryset(self, request):

        """

        Override queryset to use optimized queries

        

        Uses the new with_full_details() method from TransactionQuerySet

        for better performance in the admin interface.

        """

        qs = super().get_queryset(request)

        

        # Use the refactored QuerySet method

        return qs.with_full_details()

    

    # Add new admin actions using the refactored methods

    

    @admin.action(description=_("Export successful transactions"))

    def export_successful_transactions(self, request, queryset):

        """Export only successful transactions"""

        successful = queryset.successful()

        # ... export logic ...

    

    @admin.action(description=_("Get transaction statistics"))

    def show_statistics(self, request, queryset):

        """Show transaction statistics"""

        from wallet.services.transaction_service import TransactionService

        

        service = TransactionService()

        stats = service.get_transaction_statistics()

        

        # Display stats to admin

        self.message_user(

            request,

            f"Total Transactions: {stats['total_count']}, "

            f"Successful: {stats['successful_count']}, "

            f"Pending: {stats['pending_count']}, "

            f"Failed: {stats['failed_count']}"

        )
    
    def analytics_view(self, request):
        """Analytics view for transactions"""
        # Get aggregate metrics
        total_transactions = Transaction.objects.count()
        successful_transactions = Transaction.objects.filter(status='success').count()
        failed_transactions = Transaction.objects.filter(status='failed').count()
        pending_transactions = Transaction.objects.filter(status='pending').count()
        
        # Get amount metrics
        from django.db.models import F, DecimalField
        from django.db.models.functions import Cast
        
        amount_sum = Transaction.objects.filter(status='success').aggregate(
            total=Sum(Cast(F('amount'), output_field=DecimalField()))
        )['total'] or 0
        
        # Get transaction trend
        transactions_by_date = (
            Transaction.objects
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        
        # Get transaction types distribution
        transactions_by_type = (
            Transaction.objects
            .values('transaction_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
    
    
        
        context = {
            'title': _("Transaction Analytics"),
            'total_transactions': total_transactions,
            'successful_transactions': successful_transactions,
            'failed_transactions': failed_transactions,
            'pending_transactions': pending_transactions,
            'amount_sum': amount_sum,
            'transactions_by_date': transactions_by_date,
            'transactions_by_type': transactions_by_type,
            'opts': self.model._meta,
        }
        
        return render(request, 'admin/wallet/analytics/transaction_analytics.html', context)

    def backfill_fee_history(self, request, queryset):
        """
        Backfill fee history for selected transactions
        
        This action calculates and creates fee history records for transactions
        that don't have one yet.
        """
        from wallet.services.fee_service import FeeCalculator
        from wallet.models.fee_config import FeeHistory
        from django.contrib import messages
        
        created = 0
        skipped = 0
        errors = 0
        
        for transaction in queryset:
            # Skip if already has fee history
            if hasattr(transaction, 'fee_history'):
                skipped += 1
                continue
            
            # Skip if no fees
            if not transaction.fees or transaction.fees.amount == 0:
                skipped += 1
                continue
            
            try:
                # Create fee history from existing transaction data
                FeeHistory.objects.create(
                    transaction=transaction,
                    calculation_method='backfill',
                    original_amount=transaction.amount,
                    calculated_fee=transaction.fees,
                    fee_bearer=transaction.fee_bearer or 'platform',
                    calculation_details={
                        'backfilled': True,
                        'backfill_date': timezone.now().isoformat(),
                        'transaction_type': transaction.transaction_type,
                        'original_bearer': transaction.fee_bearer,
                    }
                )
                created += 1
                
            except Exception as e:
                errors += 1
                logger.error(
                    f"Failed to backfill fee history for transaction {transaction.id}: {str(e)}"
                )
        
        # Show result message
        msg = f"Backfilled fee history: {created} created, {skipped} skipped, {errors} errors"
        if errors > 0:
            messages.warning(request, msg)
        else:
            messages.success(request, msg)

    backfill_fee_history.short_description = "Backfill fee history for selected transactions"

class CardAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the Card model"""
    
    list_display = (
        'id', 'wallet_link', 'masked_pan', 'card_type', 
        'expiry', 'is_default', 'is_active', 'created_at'
    )
    list_filter = ('card_type', 'is_default', 'is_active', 'created_at')
    search_fields = ('id', 'wallet__id', 'wallet__user__email', 'last_four', 'card_holder_name')
    readonly_fields = (
        'id', 'wallet', 'card_type', 'last_four', 'expiry_month',
        'expiry_year', 'bin', 'masked_pan', 'paystack_authorization_code',
        'paystack_authorization_signature', 'paystack_card_data',
        'created_at', 'updated_at'
    )
    fieldsets = (
        (None, {
            'fields': ('id', 'wallet')
        }),
        (_('Card Details'), {
            'fields': (
                'card_type', 'last_four', 'expiry_month', 'expiry_year',
                'bin', 'masked_pan', 'card_holder_name', 'email'
            )
        }),
        (_('Status'), {
            'fields': ('is_default', 'is_active')
        }),
        (_('Paystack Integration'), {
            'fields': (
                'paystack_authorization_code', 'paystack_authorization_signature',
                'paystack_card_data'
            )
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def wallet_link(self, obj):
        """Link to the wallet admin"""
        url = reverse('admin:wallet_wallet_change', args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet)
    wallet_link.short_description = _("Wallet")
    
    def expiry(self, obj):
        """Format expiry for display"""
        return f"{obj.expiry_month}/{obj.expiry_year}"
    expiry.short_description = _("Expiry")


class BankAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the Bank model"""
    
    list_display = ('id', 'name', 'code', 'country', 'currency', 'is_active')
    list_filter = ('country', 'currency', 'is_active')
    search_fields = ('name', 'code', 'slug')
    readonly_fields = ('id', 'created_at', 'updated_at')
    actions = ExportMixin.actions + ['sync_from_paystack']
    
    def sync_from_paystack(self, request, queryset):
        """Sync ALL banks from Paystack (respects USE_CELERY setting)"""
        from wallet.utils.bank_sync import sync_banks_from_paystack
        from wallet.settings import get_wallet_setting
        
        try:
            # Use Celery if available, otherwise sync directly
            if get_wallet_setting('USE_CELERY'):
                from wallet.tasks import sync_banks_from_paystack_task
                
                # Queue the task
                sync_banks_from_paystack_task.delay(force_update=True)
                
                messages.success(
                    request,
                    _("Bank sync task queued. Check Celery logs for progress.")
                )
            else:
                # Sync directly (no Celery)
                created, updated, errors = sync_banks_from_paystack(force_update=True)
                
                if errors > 0:
                    messages.warning(
                        request,
                        _("Synced banks with errors: {} created, {} updated, {} errors").format(
                            created, updated, errors
                        )
                    )
                else:
                    messages.success(
                        request,
                        _("Successfully synced {} banks from Paystack ({} created, {} updated)").format(
                            created + updated, created, updated
                        )
                    )
                    
        except Exception as e:
            messages.error(
                request,
                _("Error syncing banks from Paystack: {}").format(str(e))
            )
            logger.error(f"Admin bank sync failed: {str(e)}", exc_info=True)

    sync_from_paystack.short_description = _("Sync ALL banks from Paystack")


class BankAccountAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the BankAccount model"""
    
    list_display = (
        'id', 'wallet_link', 'bank_name', 'account_number', 
        'account_name', 'is_verified', 'is_default', 'is_active'
    )
    list_filter = ('is_verified', 'is_default', 'is_active', 'account_type', 'created_at')
    search_fields = ('id', 'wallet__id', 'wallet__user__email', 'account_number', 'account_name')
    readonly_fields = (
        'id', 'wallet', 'bank', 'account_number', 'is_verified',
        'paystack_recipient_code', 'paystack_data',
        'created_at', 'updated_at'
    )
    fieldsets = (
        (None, {
            'fields': ('id', 'wallet', 'bank')
        }),
        (_('Account Details'), {
            'fields': (
                'account_number', 'account_name', 'account_type', 'bvn'
            )
        }),
        (_('Status'), {
            'fields': ('is_verified', 'is_default', 'is_active')
        }),
        (_('Paystack Integration'), {
            'fields': ('paystack_recipient_code', 'paystack_data')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at')
        }),
    )
    actions = ExportMixin.actions + ['verify_accounts', 'create_recipient_codes']
    
    def wallet_link(self, obj):
        """Link to the wallet admin"""
        url = reverse('admin:wallet_wallet_change', args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet)
    wallet_link.short_description = _("Wallet")
    
    def bank_name(self, obj):
        """Get bank name"""
        return obj.bank.name
    bank_name.short_description = _("Bank")
    
    def verify_accounts(self, request, queryset):
        """Verify selected bank accounts with Paystack"""
        wallet_service = WalletService()
        updated = 0
        
        for account in queryset.filter(is_verified=False):
            try:
                # Verify account details
                account_data = wallet_service.verify_bank_account(
                    account.account_number,
                    account.bank.code
                )
                
                # Update account name if available
                account_name = account_data.get('account_name')
                if account_name:
                    account.account_name = account_name
                    
                # Mark as verified
                account.is_verified = True
                account.save()
                
                updated += 1
            except Exception as e:
                messages.error(request, _(
                    "Error verifying account {}: {}").format(
                        account.account_number, str(e)
                    )
                )
        
        if updated:
            messages.success(request, _("Verified {} bank accounts").format(updated))
        else:
            messages.info(request, _("No bank accounts were verified"))
    verify_accounts.short_description = _("Verify selected bank accounts")
    
    def create_recipient_codes(self, request, queryset):
        """Create Paystack recipient codes for selected accounts"""
        from wallet.services.paystack_service import PaystackService
        from wallet.models import TransferRecipient
        
        paystack = PaystackService()
        updated = 0
        
        for account in queryset.filter(is_verified=True, paystack_recipient_code__isnull=True):
            try:
                # Create transfer recipient
                recipient_data = paystack.create_transfer_recipient(
                    account_type='nuban',
                    name=account.account_name,
                    account_number=account.account_number,
                    bank_code=account.bank.code
                )
                
                if recipient_data and 'recipient_code' in recipient_data:
                    # Save recipient code
                    account.paystack_recipient_code = recipient_data['recipient_code']
                    account.paystack_data = recipient_data
                    account.save()
                    
                    # Create transfer recipient record
                    TransferRecipient.objects.create(
                        wallet=account.wallet,
                        recipient_code=recipient_data['recipient_code'],
                        type='nuban',
                        name=account.account_name,
                        account_number=account.account_number,
                        bank_code=account.bank.code,
                        bank_name=account.bank.name,
                        paystack_data=recipient_data
                    )
                    
                    updated += 1
            except Exception as e:
                messages.error(request, _(
                    "Error creating recipient code for account {}: {}").format(
                        account.account_number, str(e)
                    )
                )
        
        if updated:
            messages.success(request, _("Created {} recipient codes").format(updated))
        else:
            messages.info(request, _("No recipient codes were created"))
    create_recipient_codes.short_description = _("Create Paystack recipient codes")


class WebhookEventAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the WebhookEvent model"""
    
    list_display = (
        'id', 'event_type', 'reference', 'processed', 
        'processed_at', 'is_valid', 'created_at'
    )
    list_filter = ('event_type', 'processed', 'is_valid', 'created_at')
    search_fields = ('id', 'reference', 'payload')
    readonly_fields = (
        'id', 'event_type', 'payload', 'reference', 'processed',
        'processed_at', 'signature', 'is_valid', 'transaction',
        'created_at', 'updated_at'
    )
    actions = ExportMixin.actions + ['process_events']
    
    def process_events(self, request, queryset):
        """Process selected webhook events"""
        from wallet.services.webhook_service import WebhookService
        
        webhook_service = WebhookService()
        processed = 0
        
        for event in queryset.filter(processed=False):
            try:
                # Process event
                event_type = event.event_type
                data = event.payload.get('data', {})
                
                # ✅ FIX: Try to process with transaction service - PASS webhook event!
                transaction_processed = webhook_service.transaction_service.process_paystack_webhook(
                    event_type, 
                    data,
                    event  # ✅ Pass the webhook event
                )
                
                # ✅ FIX: Try to process with settlement service - PASS webhook event!
                settlement_processed = webhook_service.settlement_service.process_paystack_webhook(
                    event_type, 
                    data,
                    event  # ✅ Pass the webhook event
                )
                
                # Mark as processed if either service handled it
                success = transaction_processed or settlement_processed
                
                if success:
                    event.processed = True
                    event.processed_at = timezone.now()
                    event.save(update_fields=['processed', 'processed_at'])
                    processed += 1
            except Exception as e:
                messages.error(request, _(
                    "Error processing webhook event {}: {}").format(
                        event.id, str(e)
                    )
                )
        
        if processed:
            messages.success(request, _("Processed {} webhook events").format(processed))
        else:
            messages.info(request, _("No webhook events were processed"))

    process_events.short_description = _("Process selected webhook events")



class WebhookEndpointAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the WebhookEndpoint model"""
    
    list_display = ('id', 'name', 'url', 'is_active', 'retry_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('id', 'name', 'url')
    filter_horizontal = ('wallets',)
    readonly_fields = ('id', 'created_at', 'updated_at')


class WebhookDeliveryAttemptAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the WebhookDeliveryAttempt model"""
    
    list_display = (
        'id', 'webhook_endpoint', 'webhook_event', 
        'is_success', 'response_code', 'attempt_number', 'created_at'
    )
    list_filter = ('is_success', 'response_code', 'attempt_number', 'created_at')
    search_fields = ('id', 'webhook_endpoint__name', 'webhook_event__reference')
    readonly_fields = (
        'id', 'webhook_endpoint', 'webhook_event', 'request_data',
        'response_code', 'response_body', 'is_success', 'attempt_number',
        'created_at', 'updated_at'
    )
    actions = ExportMixin.actions + ['retry_deliveries']
    
    def retry_deliveries(self, request, queryset):
        """Retry selected webhook delivery attempts"""
        from wallet.services.webhook_service import WebhookService
        
        webhook_service = WebhookService()
        successful = 0
        
        for attempt in queryset.filter(is_success=False):
            try:
                # Retry delivery
                success = webhook_service.retry_failed_delivery(attempt)
                
                if success:
                    successful += 1
            except Exception as e:
                messages.error(request, _(
                    "Error retrying webhook delivery {}: {}").format(
                        attempt.id, str(e)
                    )
                )
        
        if successful:
            messages.success(request, _("Successfully retried {} webhook deliveries").format(successful))
        else:
            messages.info(request, _("No webhook deliveries were successfully retried"))
    retry_deliveries.short_description = _("Retry selected webhook deliveries")


class TransferRecipientAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the TransferRecipient model"""
    
    list_display = (
        'id', 'wallet_link', 'name', 'type', 'bank_name', 
        'account_number', 'is_active', 'created_at'
    )
    list_filter = ('type', 'is_active', 'currency', 'created_at')
    search_fields = ('id', 'wallet__id', 'wallet__user__email', 'name', 'account_number', 'recipient_code')
    readonly_fields = (
        'id', 'wallet', 'recipient_code', 'type', 'name',
        'account_number', 'bank_code', 'bank_name', 'currency',
        'paystack_data', 'created_at', 'updated_at'
    )
    
    def wallet_link(self, obj):
        """Link to the wallet admin"""
        url = reverse('admin:wallet_wallet_change', args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet)
    wallet_link.short_description = _("Wallet")


class SettlementAdminForm(forms.ModelForm):
    """Form for Settlement admin"""
    
    verify_with_paystack = forms.BooleanField(
        required=False,
        help_text=_("Verify the settlement status with Paystack")
    )


class SettlementAdmin(ExportMixin, AnalyticsMixin, admin.ModelAdmin):
    """Admin for the Settlement model"""
    
    form = SettlementAdminForm
    list_display = (
        'id', 'reference', 'wallet_link', 'formatted_amount',
        'bank_account_info', 'status', 'created_at', 'settled_at'
    )
    list_filter = ('status', 'created_at', 'settled_at')
    search_fields = (
        'id', 'wallet__id', 'wallet__user__email', 'reference',
        'paystack_transfer_code', 'bank_account__account_number'
    )
    readonly_fields = (
        'id', 'wallet', 'bank_account', 'amount', 'fees',
        'status', 'reference', 'paystack_transfer_code',
        'paystack_transfer_data', 'reason', 'metadata',
        'transaction', 'settled_at', 'failure_reason',
        'created_at', 'updated_at'
    )
    actions = ExportMixin.actions + ['verify_with_paystack', 'retry_settlements']
    fieldsets = (
        (None, {
            'fields': ('id', 'reference', 'wallet', 'bank_account', 'amount', 'fees')
        }),
        (_('Status'), {
            'fields': ('status', 'settled_at', 'failure_reason')
        }),
        (_('Details'), {
            'fields': ('reason', 'metadata')
        }),
        (_('Paystack Integration'), {
            'fields': ('paystack_transfer_code', 'paystack_transfer_data', 'verify_with_paystack')
        }),
        (_('Related Entities'), {
            'fields': ('transaction',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def wallet_link(self, obj):
        """Link to the wallet admin"""
        url = reverse('admin:wallet_wallet_change', args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet)
    wallet_link.short_description = _("Wallet")
    
    def formatted_amount(self, obj):
        """Format amount for display"""
        return f"{obj.amount.amount} {obj.amount.currency.code}"
    formatted_amount.short_description = _("Amount")
    
    def bank_account_info(self, obj):
        """Display bank account information"""
        if obj.bank_account:
            return f"{obj.bank_account.bank.name} - {obj.bank_account.account_number}"
        return "-"
    bank_account_info.short_description = _("Bank Account")
    
    def save_model(self, request, obj, form, change):
        """Override save_model to handle verification"""
        super().save_model(request, obj, form, change)
        
        # Verify with Paystack if requested
        if form.cleaned_data.get('verify_with_paystack') and obj.paystack_transfer_code:
            try:
                settlement_service = SettlementService()
                settlement_service.verify_settlement(obj)
                messages.success(request, _("Settlement status verified with Paystack"))
            except Exception as e:
                messages.error(request, _("Error verifying settlement: {}").format(str(e)))
    
    def verify_with_paystack(self, request, queryset):
        """Verify selected settlements with Paystack"""
        settlement_service = SettlementService()
        updated = 0
        
        for settlement in queryset:
            if not settlement.paystack_transfer_code:
                continue
                
            try:
                settlement_service.verify_settlement(settlement)
                updated += 1
            except Exception as e:
                messages.error(request, _(
                    "Error verifying settlement {}: {}").format(
                        settlement.reference, str(e)
                    )
                )
        
        if updated:
            messages.success(request, _("Verified {} settlements with Paystack").format(updated))
        else:
            messages.info(request, _("No settlements were verified"))
    verify_with_paystack.short_description = _("Verify with Paystack")
    
    def retry_settlements(self, request, queryset):
        """Retry failed settlements"""
        settlement_service = SettlementService()
        retried = 0
        
        for settlement in queryset.filter(status='failed'):
            try:
                # Reset status and process again
                settlement.status = 'pending'
                settlement.failure_reason = None
                settlement.save(update_fields=['status', 'failure_reason'])
                
                # Process settlement
                settlement_service.process_settlement(settlement)
                retried += 1
            except Exception as e:
                messages.error(request, _(
                    "Error retrying settlement {}: {}").format(
                        settlement.reference, str(e)
                    )
                )
        
        if retried:
            messages.success(request, _("Retried {} settlements").format(retried))
        else:
            messages.info(request, _("No settlements were retried"))
    retry_settlements.short_description = _("Retry failed settlements")
    
    def analytics_view(self, request):
        """Analytics view for settlements"""
        # Get aggregate metrics
        total_settlements = Settlement.objects.count()
        successful_settlements = Settlement.objects.filter(status='success').count()
        failed_settlements = Settlement.objects.filter(status='failed').count()
        pending_settlements = Settlement.objects.filter(status='pending').count()
        
        # Get amount metrics
        from django.db.models import F, DecimalField
        from django.db.models.functions import Cast
        
        amount_sum = Settlement.objects.filter(status='success').aggregate(
            total=Sum(Cast(F('amount'), output_field=DecimalField()))
        )['total'] or 0
        
        # Get settlement trend
        settlements_by_date = (
            Settlement.objects
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        
        context = {
            'title': _("Settlement Analytics"),
            'total_settlements': total_settlements,
            'successful_settlements': successful_settlements,
            'failed_settlements': failed_settlements,
            'pending_settlements': pending_settlements,
            'amount_sum': amount_sum,
            'settlements_by_date': settlements_by_date,
            'opts': self.model._meta,
        }
        
        return render(request, 'admin/wallet/analytics/settlement_analytics.html', context)


class SettlementScheduleAdmin(ExportMixin, admin.ModelAdmin):
    """Admin for the SettlementSchedule model"""
    
    list_display = (
        'id', 'wallet_link', 'bank_account_info', 'schedule_type',
        'is_active', 'next_settlement', 'last_settlement'
    )
    list_filter = ('schedule_type', 'is_active', 'created_at')
    search_fields = (
        'id', 'wallet__id', 'wallet__user__email',
        'bank_account__account_number'
    )
    readonly_fields = (
        'id', 'wallet', 'last_settlement', 'next_settlement',
        'created_at', 'updated_at'
    )
    fieldsets = (
        (None, {
            'fields': ('id', 'wallet', 'bank_account', 'is_active')
        }),
        (_('Schedule Details'), {
            'fields': (
                'schedule_type', 'amount_threshold', 'minimum_amount',
                'maximum_amount', 'day_of_week', 'day_of_month', 
                'time_of_day'
            )
        }),
        (_('Schedule Status'), {
            'fields': ('last_settlement', 'next_settlement')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at')
        }),
    )
    actions = ExportMixin.actions + ['recalculate_next_settlement']
    
    def wallet_link(self, obj):
        """Link to the wallet admin"""
        url = reverse('admin:wallet_wallet_change', args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet)
    wallet_link.short_description = _("Wallet")
    
    def bank_account_info(self, obj):
        """Display bank account information"""
        if obj.bank_account:
            return f"{obj.bank_account.bank.name} - {obj.bank_account.account_number}"
        return "-"
    bank_account_info.short_description = _("Bank Account")
    
    def recalculate_next_settlement(self, request, queryset):
        """Recalculate next settlement date for selected schedules"""
        updated = 0
        
        for schedule in queryset:
            if schedule.schedule_type in ['daily', 'weekly', 'monthly']:
                try:
                    schedule.calculate_next_settlement()
                    updated += 1
                except Exception as e:
                    messages.error(request, _(
                        "Error recalculating next settlement for schedule {}: {}").format(
                            schedule.id, str(e)
                        )
                    )
        
        if updated:
            messages.success(request, _("Recalculated next settlement for {} schedules").format(updated))
        else:
            messages.info(request, _("No schedules were updated"))
    recalculate_next_settlement.short_description = _("Recalculate next settlement date")

@admin.register(FeeConfiguration)
class FeeConfigurationAdmin(admin.ModelAdmin):
    """Admin for Fee Configuration"""
    
    list_display = [
        'name', 'scope_display', 'transaction_type', 'payment_channel',
        'fee_type_display', 'fee_bearer', 'is_active', 'priority'
    ]
    
    list_filter = [
        'transaction_type', 'payment_channel', 'fee_type',
        'fee_bearer', 'is_active', 'created_at'
    ]
    
    search_fields = [
        'name', 'description', 'wallet__id', 'wallet__user__email'
    ]
    
    readonly_fields = [
        'id', 'created_at', 'updated_at'
    ]
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'description', 'wallet', 'is_active', 'priority')
        }),
        (_('Transaction Scope'), {
            'fields': ('transaction_type', 'payment_channel')
        }),
        (_('Fee Structure'), {
            'fields': (
                'fee_type', 'percentage_fee', 'flat_fee',
                'fee_cap', 'minimum_fee', 'waiver_threshold'
            )
        }),
        (_('Bearer Configuration'), {
            'fields': (
                'fee_bearer', 'customer_percentage', 'merchant_percentage'
            )
        }),
        (_('Validity Period'), {
            'fields': ('valid_from', 'valid_until')
        }),
        (_('Metadata'), {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        (_('System Info'), {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_configurations', 'deactivate_configurations']
    
    def scope_display(self, obj):
        """Display configuration scope"""
        if obj.wallet:
            return format_html(
                '<a href="/admin/wallet/wallet/{}/change/">{}</a>',
                obj.wallet.id,
                f"Wallet {obj.wallet.id}"
            )
        return format_html('<strong>Global</strong>')
    scope_display.short_description = _("Scope")
    
    def fee_type_display(self, obj):
        """Display fee structure summary"""
        if obj.fee_type == 'percentage':
            return f"{obj.percentage_fee}%"
        elif obj.fee_type == 'flat':
            return f"{obj.flat_fee.amount} {obj.flat_fee.currency.code}"
        else:  # hybrid
            parts = []
            if obj.percentage_fee:
                parts.append(f"{obj.percentage_fee}%")
            if obj.flat_fee.amount:
                parts.append(f"{obj.flat_fee.amount} {obj.flat_fee.currency.code}")
            return " + ".join(parts)
    fee_type_display.short_description = _("Fee Structure")
    
    def activate_configurations(self, request, queryset):
        """Activate selected configurations"""
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f"{updated} configuration(s) activated successfully."
        )
    activate_configurations.short_description = _("Activate selected configurations")
    
    def deactivate_configurations(self, request, queryset):
        """Deactivate selected configurations"""
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f"{updated} configuration(s) deactivated successfully."
        )
    deactivate_configurations.short_description = _("Deactivate selected configurations")


class FeeTierInline(admin.TabularInline):
    """Inline admin for fee tiers"""
    model = FeeTier
    extra = 1
    fields = ['min_amount', 'max_amount', 'fee_amount']


@admin.register(FeeTier)
class FeeTierAdmin(admin.ModelAdmin):
    """Admin for Fee Tier"""
    
    list_display = [
        'configuration', 'range_display', 'fee_amount', 'created_at'
    ]
    
    list_filter = [
        'configuration__transaction_type', 'created_at'
    ]
    
    search_fields = [
        'configuration__name'
    ]
    
    readonly_fields = [
        'id', 'created_at', 'updated_at'
    ]
    
    def range_display(self, obj):
        """Display amount range"""
        max_display = f"{obj.max_amount.amount}" if obj.max_amount else "∞"
        return f"{obj.min_amount.amount} - {max_display}"
    range_display.short_description = _("Amount Range")


@admin.register(FeeHistory)
class FeeHistoryAdmin(admin.ModelAdmin):
    """Admin for Fee History"""
    
    list_display = [
        'transaction_link', 'calculation_method', 'original_amount',
        'calculated_fee', 'fee_bearer', 'created_at'
    ]
    
    list_filter = [
        'calculation_method', 'fee_bearer', 'created_at'
    ]
    
    search_fields = [
        'transaction__reference', 'transaction__wallet__id'
    ]
    
    readonly_fields = [
        'id', 'transaction', 'configuration_used', 'calculation_method',
        'original_amount', 'calculated_fee', 'fee_bearer',
        'calculation_details', 'created_at', 'updated_at'
    ]
    
    fieldsets = (
        (_('Transaction Info'), {
            'fields': ('transaction', 'configuration_used')
        }),
        (_('Calculation Details'), {
            'fields': (
                'calculation_method', 'original_amount',
                'calculated_fee', 'fee_bearer'
            )
        }),
        (_('Breakdown'), {
            'fields': ('calculation_details',),
            'classes': ('collapse',)
        }),
        (_('System Info'), {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def transaction_link(self, obj):
        """Link to transaction"""
        return format_html(
            '<a href="/admin/wallet/transaction/{}/change/">{}</a>',
            obj.transaction.id,
            obj.transaction.reference
        )
    transaction_link.short_description = _("Transaction")
    
    def has_add_permission(self, request):
        """Fee history is automatically created, don't allow manual creation"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Fee history is read-only"""
        return False


# Register admin classes
admin.site.register(Wallet, WalletAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Card, CardAdmin)
admin.site.register(Bank, BankAdmin)
admin.site.register(BankAccount, BankAccountAdmin)
admin.site.register(WebhookEvent, WebhookEventAdmin)
admin.site.register(WebhookEndpoint, WebhookEndpointAdmin)
admin.site.register(WebhookDeliveryAttempt, WebhookDeliveryAttemptAdmin)
admin.site.register(TransferRecipient, TransferRecipientAdmin)
admin.site.register(Settlement, SettlementAdmin)
admin.site.register(SettlementSchedule, SettlementScheduleAdmin)
