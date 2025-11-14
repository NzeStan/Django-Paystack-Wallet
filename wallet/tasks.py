# import logging
# from decimal import Decimal
# from celery import shared_task
# from django.apps import apps
# from django.conf import settings
# from django.utils import timezone
# from django.db import transaction

# from wallet.settings import get_wallet_setting
# from wallet.services.wallet_service import WalletService
# from wallet.services.settlement_service import SettlementService
# from wallet.services.webhook_service import WebhookService


# logger = logging.getLogger(__name__)


# @shared_task
# def create_wallet_for_user_task(user_id):
#     """
#     Create a wallet for a user (async task)
    
#     Args:
#         user_id: User ID
#     """
#     # Get user model
#     User = apps.get_model(get_wallet_setting('USER_MODEL'))
    
#     try:
#         # Get user instance
#         user = User.objects.get(pk=user_id)
        
#         # Create wallet
#         wallet_service = WalletService()
#         wallet = wallet_service.get_wallet(user)
        
#         logger.info(f"Created wallet {wallet.id} for user {user_id}")
#         return str(wallet.id)
#     except Exception as e:
#         logger.error(f"Error creating wallet for user {user_id}: {str(e)}")
#         raise


# @shared_task
# def create_dedicated_account_task(wallet_id):
#     """
#     Create a dedicated virtual account for a wallet (async task)
    
#     Args:
#         wallet_id: Wallet ID
#     """
#     # Get wallet model
#     Wallet = apps.get_model('wallet', 'Wallet')
    
#     try:
#         # Get wallet instance
#         wallet = Wallet.objects.get(pk=wallet_id)
        
#         # Create dedicated account
#         wallet_service = WalletService()
#         result = wallet_service.create_dedicated_account(wallet)
        
#         logger.info(f"Created dedicated account for wallet {wallet_id}: {result}")
#         return result
#     except Exception as e:
#         logger.error(f"Error creating dedicated account for wallet {wallet_id}: {str(e)}")
#         raise


# @shared_task
# def process_wallet_settlement_schedules_task(wallet_id):
#     """
#     Process settlement schedules for a wallet (async task)
    
#     Args:
#         wallet_id: Wallet ID
#     """
#     # Get models
#     Wallet = apps.get_model('wallet', 'Wallet')
#     SettlementSchedule = apps.get_model('wallet', 'SettlementSchedule')
    
#     try:
#         # Get wallet instance
#         wallet = Wallet.objects.get(pk=wallet_id)
        
#         # Get settlement service
#         settlement_service = SettlementService()
        
#         # Find threshold schedules for this wallet
#         schedules = SettlementSchedule.objects.filter(
#             wallet=wallet,
#             is_active=True,
#             schedule_type='threshold'
#         ).exclude(
#             amount_threshold=None
#         ).select_related('bank_account')
        
#         count = 0
#         for schedule in schedules:
#             # Check if balance exceeds threshold
#             if wallet.balance.amount >= schedule.amount_threshold.amount:
#                 amount = settlement_service._calculate_settlement_amount(schedule)
                
#                 if amount > 0:
#                     with transaction.atomic():
#                         settlement_service.create_settlement(
#                             wallet=wallet,
#                             bank_account=schedule.bank_account,
#                             amount=amount,
#                             reason="Automatic threshold-based settlement",
#                             metadata={
#                                 'schedule_id': str(schedule.id),
#                                 'schedule_type': 'threshold',
#                                 'threshold': str(schedule.amount_threshold.amount)
#                             }
#                         )
                        
#                         # Update last settlement date
#                         schedule.last_settlement = timezone.now()
#                         schedule.save(update_fields=['last_settlement'])
                        
#                     count += 1
        
#         logger.info(f"Processed {count} settlement schedules for wallet {wallet_id}")
#         return count
#     except Exception as e:
#         logger.error(f"Error processing settlement schedules for wallet {wallet_id}: {str(e)}")
#         raise


# @shared_task
# def process_due_settlement_schedules_task():
#     """
#     Process all due settlement schedules (scheduled task)
#     """
#     try:
#         # Get settlement service
#         settlement_service = SettlementService()
        
#         # Process due settlements
#         count = settlement_service.process_due_settlements()
        
#         logger.info(f"Processed {count} due settlement schedules")
#         return count
#     except Exception as e:
#         logger.error(f"Error processing due settlement schedules: {str(e)}")
#         raise


# @shared_task
# def retry_failed_webhook_deliveries_task():
#     """
#     Retry all failed webhook deliveries (scheduled task)
#     """
#     try:
#         # Get webhook service
#         webhook_service = WebhookService()
        
#         # Retry failed deliveries
#         count = webhook_service.retry_all_failed_deliveries()
        
#         logger.info(f"Retried {count} failed webhook deliveries successfully")
#         return count
#     except Exception as e:
#         logger.error(f"Error retrying failed webhook deliveries: {str(e)}")
#         raise


# @shared_task
# def sync_banks_from_paystack_task():
#     """
#     Sync banks from Paystack (scheduled task)
#     """
#     # Get models
#     Bank = apps.get_model('wallet', 'Bank')
    
#     try:
#         # Get wallet service
#         wallet_service = WalletService()
        
#         # Get banks from Paystack
#         banks_data = wallet_service.list_banks()
        
#         # Update or create banks
#         count = 0
#         for bank_data in banks_data:
#             bank_code = bank_data.get('code')
#             if not bank_code:
#                 continue
                
#             bank, created = Bank.objects.update_or_create(
#                 code=bank_code,
#                 defaults={
#                     'name': bank_data.get('name', ''),
#                     'slug': bank_data.get('slug', bank_code.lower()),
#                     'country': bank_data.get('country', 'NG'),
#                     'currency': bank_data.get('currency', 'NGN'),
#                     'type': bank_data.get('type'),
#                     'is_active': bank_data.get('active', True),
#                     'paystack_data': bank_data
#                 }
#             )
            
#             count += 1
        
#         logger.info(f"Synced {count} banks from Paystack")
#         return count
#     except Exception as e:
#         logger.error(f"Error syncing banks from Paystack: {str(e)}")
#         raise


# @shared_task
# def verify_pending_settlements_task():
#     """
#     Verify all pending settlements (scheduled task)
#     """
#     # Get models
#     Settlement = apps.get_model('wallet', 'Settlement')
    
#     try:
#         # Get settlement service
#         settlement_service = SettlementService()
        
#         # Get pending settlements
#         from wallet.constants import SETTLEMENT_STATUS_PENDING
#         pending_settlements = Settlement.objects.filter(
#             status=SETTLEMENT_STATUS_PENDING
#         ).exclude(
#             paystack_transfer_code=None
#         )
        
#         count = 0
#         for settlement in pending_settlements:
#             try:
#                 # Verify settlement status
#                 updated_settlement = settlement_service.verify_settlement(settlement)
                
#                 # Count settlements that were updated to success or failed
#                 from wallet.constants import SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED
#                 if updated_settlement.status in [SETTLEMENT_STATUS_SUCCESS, SETTLEMENT_STATUS_FAILED]:
#                     count += 1
#             except Exception as e:
#                 logger.error(f"Error verifying settlement {settlement.id}: {str(e)}")
        
#         logger.info(f"Verified {count} pending settlements")
#         return count
#     except Exception as e:
#         logger.error(f"Error verifying pending settlements: {str(e)}")
#         raise


# @shared_task
# def reset_daily_transaction_limits_task():
#     """
#     Reset daily transaction limits for all wallets (scheduled task)
#     """
#     # Get models
#     Wallet = apps.get_model('wallet', 'Wallet')
    
#     try:
#         # Get today's date
#         today = timezone.now().date()
        
#         # Find wallets with outdated daily limits
#         wallets = Wallet.objects.exclude(daily_transaction_reset=today)
        
#         # Reset limits
#         count = wallets.update(
#             daily_transaction_total=0,
#             daily_transaction_count=0,
#             daily_transaction_reset=today
#         )
        
#         logger.info(f"Reset daily transaction limits for {count} wallets")
#         return count
#     except Exception as e:
#         logger.error(f"Error resetting daily transaction limits: {str(e)}")
#         raise


# @shared_task
# def verify_bank_accounts_task():
#     """
#     Verify unverified bank accounts (scheduled task)
#     """
#     # Get models
#     BankAccount = apps.get_model('wallet', 'BankAccount')
    
#     try:
#         # Get wallet service
#         wallet_service = WalletService()
        
#         # Find unverified bank accounts
#         bank_accounts = BankAccount.objects.filter(
#             is_verified=False,
#             is_active=True
#         ).select_related('bank')
        
#         count = 0
#         for bank_account in bank_accounts:
#             try:
#                 # Verify account details
#                 account_data = wallet_service.verify_bank_account(
#                     bank_account.account_number,
#                     bank_account.bank.code
#                 )
                
#                 # Update account name if available
#                 account_name = account_data.get('account_name')
#                 if account_name:
#                     bank_account.account_name = account_name
                    
#                 # Mark as verified
#                 bank_account.is_verified = True
#                 bank_account.save(update_fields=['account_name', 'is_verified'])
                
#                 # Create transfer recipient if missing
#                 if not bank_account.paystack_recipient_code:
#                     from wallet.services.paystack_service import PaystackService
#                     paystack = PaystackService()
                    
#                     recipient_data = paystack.create_transfer_recipient(
#                         account_type='nuban',
#                         name=bank_account.account_name,
#                         account_number=bank_account.account_number,
#                         bank_code=bank_account.bank.code,
#                         currency=get_wallet_setting('CURRENCY')
#                     )
                    
#                     if recipient_data and 'recipient_code' in recipient_data:
#                         bank_account.paystack_recipient_code = recipient_data['recipient_code']
#                         bank_account.paystack_data = recipient_data
#                         bank_account.save(update_fields=['paystack_recipient_code', 'paystack_data'])
                        
#                         # Create transfer recipient record
#                         TransferRecipient = apps.get_model('wallet', 'TransferRecipient')
#                         TransferRecipient.objects.create(
#                             wallet=bank_account.wallet,
#                             recipient_code=recipient_data['recipient_code'],
#                             type='nuban',
#                             name=bank_account.account_name,
#                             account_number=bank_account.account_number,
#                             bank_code=bank_account.bank.code,
#                             bank_name=bank_account.bank.name,
#                             currency=get_wallet_setting('CURRENCY'),
#                             paystack_data=recipient_data
#                         )
                
#                 count += 1
#             except Exception as e:
#                 logger.error(f"Error verifying bank account {bank_account.id}: {str(e)}")
        
#         logger.info(f"Verified {count} bank accounts")
#         return count
#     except Exception as e:
#         logger.error(f"Error verifying bank accounts: {str(e)}")
#         raise


# @shared_task
# def check_expired_cards_task():
#     """
#     Check for expired cards and mark them as inactive (scheduled task)
#     """
#     # Get models
#     Card = apps.get_model('wallet', 'Card')
    
#     try:
#         # Get today's date
#         now = timezone.now()
#         current_month = now.month
#         current_year = now.year
        
#         # Find expired cards
#         expired_cards = Card.objects.filter(
#             is_active=True
#         ).filter(
#             # Cards that expired in previous years
#             expiry_year__lt=current_year
#         ).union(
#             # Cards that expired in previous months of current year
#             Card.objects.filter(
#                 expiry_year=current_year,
#                 expiry_month__lt=current_month,
#                 is_active=True
#             )
#         )
        
#         # Mark as inactive
#         count = 0
#         for card in expired_cards:
#             try:
#                 card.is_active = False
                
#                 # Clear default status
#                 if card.is_default:
#                     card.is_default = False
                    
#                 card.save(update_fields=['is_active', 'is_default'])
                
#                 # Set another card as default if available
#                 if card.is_default:
#                     active_card = Card.objects.filter(
#                         wallet=card.wallet,
#                         is_active=True
#                     ).first()
                    
#                     if active_card:
#                         active_card.set_as_default()
                
#                 count += 1
#             except Exception as e:
#                 logger.error(f"Error processing expired card {card.id}: {str(e)}")
        
#         logger.info(f"Marked {count} expired cards as inactive")
#         return count
#     except Exception as e:
#         logger.error(f"Error checking expired cards: {str(e)}")
#         raise