from django.contrib.auth import views as auth_views
from django.urls import path

from shop import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('send/', views.send, name='send'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('cards/', views.cards, name='cards'),
    path('history/', views.history, name='history'),
    path('shop/', views.shop, name='shop'),
    path('shop/sell/', views.sell, name='sell'),
    path('shop/buy/<int:product_id>/', views.buy, name='buy'),
    path('orders/', views.orders, name='orders'),
    path('orders/<int:order_id>/confirm/', views.confirm_delivery, name='confirm-delivery'),
    path('orders/<int:order_id>/refund/', views.refund_order, name='refund-order'),
    path('developer/', views.developer, name='developer'),
    path('signup/', views.signup, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='shop/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
