"""
A tiny marketplace used to show how *your* app integrates with the wallet:
buyers pay sellers from their wallet, with the money held in escrow until the
buyer confirms delivery.
"""
from django.conf import settings
from django.db import models


class Product(models.Model):
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} (NGN {self.price})"


class Order(models.Model):
    STATUS_IN_ESCROW = 'in_escrow'
    STATUS_COMPLETED = 'completed'
    STATUS_REFUNDED = 'refunded'
    STATUSES = [
        (STATUS_IN_ESCROW, 'Paid - held in escrow'),
        (STATUS_COMPLETED, 'Delivered - seller paid'),
        (STATUS_REFUNDED, 'Cancelled - buyer refunded'),
    ]

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='orders')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # The buyer's wallet transaction (debit held in escrow)
    payment = models.OneToOneField('wallet.Transaction', on_delete=models.PROTECT, related_name='order')
    status = models.CharField(max_length=20, choices=STATUSES, default=STATUS_IN_ESCROW)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.pk} - {self.product.name}"
