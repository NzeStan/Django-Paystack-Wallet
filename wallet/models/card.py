"""
Django Paystack Wallet - Card Model
Refactored with Django best practices and query optimizations
"""
from datetime import datetime
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from wallet.models.base import BaseModel
from wallet.constants import CARD_TYPES, CARD_TYPE_VISA


# ==========================================
# CARD QUERYSET AND MANAGER
# ==========================================

class CardQuerySet(models.QuerySet):
    """Custom QuerySet for Card model with optimized queries"""
    
    def active(self):
        """Return only active cards"""
        return self.filter(is_active=True)
    
    def inactive(self):
        """Return only inactive cards"""
        return self.filter(is_active=False)
    
    def defaults(self):
        """Return only default cards"""
        return self.filter(is_default=True)
    
    def expired(self):
        """Return only expired cards"""
        now = datetime.now()
        current_year = now.year
        current_month = now.month
        
        # Cards where year is less than current year
        # OR year equals current year but month is less than current month
        return self.filter(
            models.Q(expiry_year__lt=str(current_year)) |
            models.Q(
                expiry_year=str(current_year),
                expiry_month__lt=str(current_month).zfill(2)
            )
        )
    
    def not_expired(self):
        """Return only non-expired cards"""
        now = datetime.now()
        current_year = now.year
        current_month = now.month
        
        # Cards where year is greater than current year
        # OR year equals current year and month is greater than or equal to current month
        return self.filter(
            models.Q(expiry_year__gt=str(current_year)) |
            models.Q(
                expiry_year=str(current_year),
                expiry_month__gte=str(current_month).zfill(2)
            )
        )
    
    def by_wallet(self, wallet):
        """
        Filter cards by wallet
        
        Args:
            wallet: Wallet instance
            
        Returns:
            QuerySet: Filtered cards
        """
        return self.filter(wallet=wallet)
    
    def by_card_type(self, card_type):
        """
        Filter cards by card type
        
        Args:
            card_type (str): Card type
            
        Returns:
            QuerySet: Filtered cards
        """
        return self.filter(card_type=card_type)
    
    def by_last_four(self, last_four):
        """
        Filter cards by last four digits
        
        Args:
            last_four (str): Last four digits
            
        Returns:
            QuerySet: Filtered cards
        """
        return self.filter(last_four=last_four)
    
    def with_wallet_details(self):
        """Prefetch wallet and user details to avoid N+1 queries"""
        return self.select_related('wallet', 'wallet__user')
    
    def with_full_details(self):
        """Prefetch all related data for comprehensive views"""
        return self.select_related(
            'wallet',
            'wallet__user'
        ).prefetch_related('transactions')
    
    def with_transaction_count(self):
        """Annotate cards with transaction count"""
        from django.db.models import Count
        return self.annotate(transaction_count=Count('transactions'))
    
    def with_statistics(self):
        """Annotate cards with comprehensive statistics"""
        from django.db.models import Count, Sum, Q, Avg
        from wallet.constants import TRANSACTION_STATUS_SUCCESS
        
        return self.annotate(
            total_transactions=Count('transactions'),
            successful_transactions=Count(
                'transactions',
                filter=Q(transactions__status=TRANSACTION_STATUS_SUCCESS)
            ),
            total_amount=Sum(
                'transactions__amount',
                filter=Q(transactions__status=TRANSACTION_STATUS_SUCCESS)
            ),
            average_amount=Avg(
                'transactions__amount',
                filter=Q(transactions__status=TRANSACTION_STATUS_SUCCESS)
            )
        )
    
    def search(self, query):
        """
        Search cards by last four digits or holder name
        
        Args:
            query (str): Search query
            
        Returns:
            QuerySet: Filtered cards
        """
        from django.db.models import Q
        return self.filter(
            Q(last_four__icontains=query) |
            Q(card_holder_name__icontains=query) |
            Q(bin__icontains=query)
        )


class CardManager(models.Manager):
    """Custom Manager for Card model"""
    
    def get_queryset(self):
        """Return custom queryset"""
        return CardQuerySet(self.model, using=self._db)
    
    def active(self):
        """Return only active cards"""
        return self.get_queryset().active()
    
    def inactive(self):
        """Return only inactive cards"""
        return self.get_queryset().inactive()
    
    def defaults(self):
        """Return only default cards"""
        return self.get_queryset().defaults()
    
    def expired(self):
        """Return only expired cards"""
        return self.get_queryset().expired()
    
    def not_expired(self):
        """Return only non-expired cards"""
        return self.get_queryset().not_expired()
    
    def for_wallet(self, wallet):
        """Get all cards for a specific wallet"""
        return self.get_queryset().by_wallet(wallet)
    
    def by_card_type(self, card_type):
        """Get cards by card type"""
        return self.get_queryset().by_card_type(card_type)
    
    def by_last_four(self, last_four):
        """Get cards by last four digits"""
        return self.get_queryset().by_last_four(last_four)
    
    def with_wallet_details(self):
        """Get cards with wallet details"""
        return self.get_queryset().with_wallet_details()
    
    def with_full_details(self):
        """Get cards with full related data"""
        return self.get_queryset().with_full_details()
    
    def search(self, query):
        """Search cards"""
        return self.get_queryset().search(query)
    
    def get_by_authorization_code(self, authorization_code):
        """
        Get card by Paystack authorization code
        
        Args:
            authorization_code (str): Paystack authorization code
            
        Returns:
            Card: Card instance
            
        Raises:
            Card.DoesNotExist: If card not found
        """
        return self.get(paystack_authorization_code=authorization_code)


# ==========================================
# MODEL
# ==========================================

class Card(BaseModel):
    """
    Card model for storing payment card information
    
    This model stores tokenized card information from Paystack for
    recurring payments. It never stores full card numbers or CVV codes.
    """
    
    # Relationships
    wallet = models.ForeignKey(
        'wallet.Wallet',
        on_delete=models.CASCADE,
        related_name='cards',
        db_index=True,
        verbose_name=_('Wallet'),
        help_text=_('Wallet that owns this card')
    )
    
    # Card Details
    card_type = models.CharField(
        max_length=20,
        choices=CARD_TYPES,
        default=CARD_TYPE_VISA,
        db_index=True,
        verbose_name=_('Card type'),
        help_text=_('Type of card (Visa, Mastercard, etc.)')
    )
    last_four = models.CharField(
        max_length=4,
        db_index=True,
        verbose_name=_('Last four digits'),
        help_text=_('Last four digits of the card number')
    )
    expiry_month = models.CharField(
        max_length=2,
        verbose_name=_('Expiry month'),
        help_text=_('Card expiry month (MM)')
    )
    expiry_year = models.CharField(
        max_length=4,
        verbose_name=_('Expiry year'),
        help_text=_('Card expiry year (YYYY)')
    )
    bin = models.CharField(
        max_length=6,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Bank Identification Number (BIN)'),
        help_text=_('First 6 digits of the card number')
    )
    
    # Cardholder Information
    card_holder_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('Card holder name'),
        help_text=_('Name on the card')
    )
    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_('Email'),
        help_text=_('Email associated with the card')
    )
    
    # Status
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_('Is default'),
        help_text=_('Whether this is the default card for the wallet')
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_('Is active'),
        help_text=_('Whether the card is currently active')
    )
    
    # Paystack Integration
    paystack_authorization_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_('Paystack authorization code'),
        help_text=_('Paystack authorization code for charging the card')
    )
    paystack_authorization_signature = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('Paystack authorization signature'),
        help_text=_('Paystack authorization signature')
    )
    paystack_card_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_('Paystack card data'),
        help_text=_('Additional card data from Paystack API')
    )
    
    # Custom Manager
    objects = CardManager()
    
    class Meta:
        verbose_name = _('Card')
        verbose_name_plural = _('Cards')
        ordering = ['-is_default', '-created_at']
        unique_together = ('wallet', 'paystack_authorization_code')
        indexes = [
            models.Index(fields=['wallet', 'is_default'], name='card_wallet_default_idx'),
            models.Index(fields=['wallet', 'is_active'], name='card_wallet_active_idx'),
            models.Index(fields=['paystack_authorization_code'], name='card_auth_code_idx'),
            models.Index(fields=['last_four'], name='card_last_four_idx'),
            models.Index(fields=['card_type'], name='card_type_idx'),
        ]
    
    def __str__(self):
        """String representation of the card"""
        return f"{self.get_card_type_display()} **** **** **** {self.last_four}"
    
    def __repr__(self):
        """Developer-friendly representation"""
        return (
            f"<Card id={self.id} wallet_id={self.wallet_id} "
            f"type={self.card_type} last_four={self.last_four}>"
        )
    
    def save(self, *args, **kwargs):
        """
        Override save to handle default card logic
        
        If this card is being set as default, unset any other default
        cards for this wallet.
        """
        if self.is_default:
            # Unset other default cards for this wallet
            Card.objects.filter(
                wallet=self.wallet,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        
        super().save(*args, **kwargs)
    
    # ==========================================
    # PUBLIC METHODS
    # ==========================================
    
    @transaction.atomic
    def set_as_default(self):
        """
        Set this card as the default card for the wallet
        
        This method ensures that only one card is set as default
        per wallet by unsetting other default cards atomically.
        
        Returns:
            None
        """
        # Unset other default cards
        Card.objects.filter(
            wallet=self.wallet,
            is_default=True
        ).exclude(pk=self.pk).update(is_default=False)
        
        # Set this as default
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])
    
    @transaction.atomic
    def remove(self):
        """
        Mark the card as inactive instead of deleting it
        
        This is a soft delete that preserves historical data while
        preventing the card from being used in new transactions.
        If this was the default card, another active card will
        be set as default.
        
        Returns:
            None
        """
        was_default = self.is_default
        
        # Mark as inactive and remove default status
        self.is_active = False
        self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
        
        # If this was default, set another active card as default
        if was_default:
            new_default = Card.objects.filter(
                wallet=self.wallet,
                is_active=True
            ).exclude(pk=self.pk).first()
            
            if new_default:
                new_default.set_as_default()
    
    @transaction.atomic
    def activate(self):
        """
        Activate the card
        
        Returns:
            None
        """
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])
    
    @transaction.atomic
    def deactivate(self):
        """
        Deactivate the card
        
        Returns:
            None
        """
        self.is_active = False
        if self.is_default:
            self.is_default = False
        self.save(update_fields=['is_active', 'is_default', 'updated_at'])
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def is_expired(self):
        """
        Check if the card is expired
        
        Returns:
            bool: True if expired, False otherwise
        """
        now = datetime.now()
        return (
            int(self.expiry_year) < now.year or 
            (int(self.expiry_year) == now.year and int(self.expiry_month) < now.month)
        )
    
    @property
    def masked_pan(self):
        """
        Return masked PAN (Primary Account Number)
        
        Returns:
            str: Masked card number (e.g., '4123 **** **** 4567')
        """
        if self.bin:
            return f"{self.bin} {'*' * 4} {'*' * 4} {self.last_four}"
        return f"{'*' * 4} {'*' * 4} {'*' * 4} {self.last_four}"
    
    @property
    def expiry(self):
        """
        Get formatted expiry date
        
        Returns:
            str: Expiry date in MM/YYYY format
        """
        return f"{self.expiry_month}/{self.expiry_year}"
    
    @property
    def display_name(self):
        """
        Get display name for the card
        
        Returns:
            str: Display name
        """
        card_type = self.get_card_type_display()
        if self.card_holder_name:
            return f"{card_type} ({self.card_holder_name}) **** {self.last_four}"
        return f"{card_type} **** {self.last_four}"
    
    @property
    def is_valid(self):
        """
        Check if the card is valid (active and not expired)
        
        Returns:
            bool: True if valid, False otherwise
        """
        return self.is_active and not self.is_expired