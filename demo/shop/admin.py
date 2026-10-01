from django.contrib import admin

from shop.models import Order, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'seller', 'price', 'created_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'buyer', 'amount', 'status', 'created_at')
    list_filter = ('status',)
    readonly_fields = ('payment',)
