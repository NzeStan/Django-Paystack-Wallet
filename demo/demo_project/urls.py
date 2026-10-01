from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('wallet/', include('wallet.urls')),     # the package: API, webhook, callback
    path('', include('shop.urls')),              # the demo UI
]
