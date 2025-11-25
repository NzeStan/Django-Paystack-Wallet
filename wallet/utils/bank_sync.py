"""
Django Paystack Wallet - Bank Synchronization Utilities

This module provides utility functions for syncing banks from Paystack.
These functions work with or without Celery, following the package's
flexible architecture pattern.

Usage:
    # Direct usage (no Celery required)
    from wallet.utils.bank_sync import sync_banks_from_paystack
    created, updated, errors = sync_banks_from_paystack()
    
    # Ensure banks exist
    from wallet.utils.bank_sync import ensure_banks_exist
    if not ensure_banks_exist():
        print("Warning: Could not sync banks")
"""
import logging
from typing import Tuple
from wallet.models import Bank
from wallet.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


def sync_banks_from_paystack(force_update: bool = False) -> Tuple[int, int, int]:
    """
    Sync banks from Paystack to database
    
    This is the core utility function that works with or without Celery.
    It fetches all banks from the Paystack API and creates/updates them
    in the database.
    
    Args:
        force_update (bool): If True, updates existing banks even if they exist.
                           If False, skips existing banks (faster for initial sync).
        
    Returns:
        tuple: (created_count, updated_count, error_count)
        
    Raises:
        Exception: If Paystack API call fails completely
        
    Example:
        >>> created, updated, errors = sync_banks_from_paystack()
        >>> print(f"Synced {created + updated} banks ({created} new)")
    """
    logger.info("Starting bank synchronization from Paystack...")
    
    try:
        # Initialize wallet service
        wallet_service = WalletService()
        
        # Fetch banks from Paystack
        banks_data = wallet_service.list_banks()
        
        if not banks_data:
            logger.warning("No banks returned from Paystack API")
            return (0, 0, 0)
        
        logger.info(f"Fetched {len(banks_data)} banks from Paystack API")
        
        # Process each bank
        created_count = 0
        updated_count = 0
        error_count = 0
        
        for bank_data in banks_data:
            bank_code = bank_data.get('code')
            
            if not bank_code:
                logger.warning(f"Skipping bank without code: {bank_data.get('name')}")
                error_count += 1
                continue
            
            try:
                # Prepare bank data
                bank_defaults = {
                    'name': bank_data.get('name', ''),
                    'slug': bank_data.get('slug', bank_code.lower()),
                    'country': bank_data.get('country', 'NG'),
                    'currency': bank_data.get('currency', 'NGN'),
                    'type': bank_data.get('type'),
                    'is_active': bank_data.get('active', True),
                    'paystack_data': bank_data
                }
                
                # Check if bank exists (optimization for non-force updates)
                if not force_update:
                    existing = Bank.objects.filter(code=bank_code).exists()
                    if existing:
                        logger.debug(f"Bank {bank_code} already exists, skipping")
                        continue
                
                # Create or update bank
                bank, created = Bank.objects.update_or_create(
                    code=bank_code,
                    defaults=bank_defaults
                )
                
                if created:
                    logger.info(f"Created bank: {bank.name} ({bank.code})")
                    created_count += 1
                else:
                    logger.info(f"Updated bank: {bank.name} ({bank.code})")
                    updated_count += 1
                    
            except Exception as e:
                logger.error(
                    f"Error processing bank {bank_code}: {str(e)}",
                    exc_info=True
                )
                error_count += 1
        
        logger.info(
            f"Bank sync completed: {created_count} created, "
            f"{updated_count} updated, {error_count} errors"
        )
        
        return (created_count, updated_count, error_count)
        
    except Exception as e:
        logger.error(f"Failed to sync banks from Paystack: {str(e)}", exc_info=True)
        raise


def ensure_banks_exist() -> bool:
    """
    Ensure at least one bank exists in the database
    
    This is a convenience function for initialization checks. If no banks
    exist in the database, it attempts to sync them from Paystack.
    
    Returns:
        bool: True if banks exist or were successfully synced, False otherwise
        
    Example:
        >>> from wallet.utils.bank_sync import ensure_banks_exist
        >>> if not ensure_banks_exist():
        ...     print("Warning: No banks available!")
    """
    # Check if banks already exist
    if Bank.objects.exists():
        logger.debug("Banks already exist in database")
        return True
    
    logger.info("No banks found in database, attempting to sync from Paystack...")
    
    try:
        created, updated, errors = sync_banks_from_paystack()
        
        if created > 0:
            logger.info(f"Successfully synced {created} banks from Paystack")
            return True
        else:
            logger.warning("No banks were created during sync")
            return False
            
    except Exception as e:
        logger.error(f"Failed to ensure banks exist: {str(e)}")
        return False