from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shop'
    verbose_name = 'Demo shop'

    def ready(self):
        from shop import receivers  # noqa: F401  (connects wallet signal receivers)
