"""
Demo pages.

Wallet pages are thin HTML shells whose JavaScript calls the package's REST API
(/wallet/api/...) - so you test the API exactly as a web or mobile client would.
The shop pages call the service layer from Django views - the way your own
backend code would use the package.
"""
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from shop.models import Order, Product
from wallet.conf import wallet_settings
from wallet.exceptions import PinRequired, WalletError
from wallet.models import WebhookEvent
from wallet.services import TransactionService, WalletService


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text='Paystack needs an email for checkout.')
    first_name = forms.CharField(max_length=50)
    last_name = forms.CharField(max_length=50)
    phone_number = forms.CharField(max_length=20, required=False,
                                   help_text='Optional. Others can send you money with it.')

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email', 'first_name', 'last_name')


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        service = WalletService()
        wallet = service.get_wallet(user)
        if form.cleaned_data.get('phone_number'):
            try:
                service.set_phone_number(wallet, form.cleaned_data['phone_number'])
            except WalletError as exc:
                messages.warning(request, f"Phone number not saved: {exc.message}")
        login(request, user)
        messages.success(request, 'Welcome! Your wallet is ready.')
        return redirect('dashboard')
    return render(request, 'shop/signup.html', {'form': form})


# ---------------------------------------------------------------------------
# Wallet pages (JavaScript talks to /wallet/api/)
# ---------------------------------------------------------------------------

def _page(template):
    @login_required
    @ensure_csrf_cookie
    def view(request):
        return render(request, f'shop/{template}.html')
    view.__name__ = template
    return view


dashboard = _page('dashboard')
send = _page('send')
withdraw = _page('withdraw')
cards = _page('cards')
history = _page('history')


# ---------------------------------------------------------------------------
# Marketplace (server-side calls into the service layer)
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
def shop(request):
    products = Product.objects.select_related('seller').all()
    return render(request, 'shop/shop.html', {'products': products})


@login_required
@require_POST
def sell(request):
    try:
        price = Decimal(request.POST.get('price', ''))
    except InvalidOperation:
        price = Decimal('0')
    name = (request.POST.get('name') or '').strip()
    if not name or price <= 0:
        messages.error(request, 'Give the product a name and a positive price.')
    else:
        Product.objects.create(seller=request.user, name=name, price=price,
                               description=request.POST.get('description', '')[:255])
        messages.success(request, f'"{name}" is now listed.')
    return redirect('shop')


@login_required
@require_POST
def buy(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    if product.seller_id == request.user.pk:
        messages.error(request, "You can't buy your own product.")
        return redirect('shop')
    service = WalletService()
    try:
        buyer_wallet = service.get_wallet(request.user)
        if wallet_settings.REQUIRE_TRANSACTION_PIN:
            if not request.POST.get('pin'):
                raise PinRequired()
            buyer_wallet.verify_pin(request.POST['pin'])
        payment = service.pay(
            buyer_wallet, product.price, merchant_wallet=service.get_wallet(product.seller), escrow=True,
            description=f"Order: {product.name}", metadata={'product_id': product.pk},
        )
        Order.objects.create(buyer=request.user, product=product, amount=product.price, payment=payment)
        messages.success(request, f'Paid NGN {product.price}. The money is held in escrow until you confirm '
                                  f'delivery on the Orders page.')
    except WalletError as exc:
        messages.error(request, exc.message)
    return redirect('orders')


@login_required
def orders(request):
    return render(request, 'shop/orders.html', {
        'purchases': Order.objects.filter(buyer=request.user).select_related('product', 'product__seller'),
        'sales': Order.objects.filter(product__seller=request.user).select_related('product', 'buyer'),
    })


@login_required
@require_POST
def confirm_delivery(request, order_id):
    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    try:
        WalletService().release_payment(order.payment, performed_by=request.user)
        messages.success(request, 'Delivery confirmed. The seller has been paid.')
    except WalletError as exc:
        messages.error(request, exc.message)
    return redirect('orders')


@login_required
@require_POST
def refund_order(request, order_id):
    """The seller can't deliver: refund the buyer from escrow (policy decided by *your* code)."""
    order = get_object_or_404(Order, pk=order_id, product__seller=request.user)
    try:
        TransactionService().cancel_transaction(order.payment, 'Seller could not fulfil the order',
                                                performed_by=request.user)
        messages.success(request, 'Order cancelled and the buyer refunded.')
    except WalletError as exc:
        messages.error(request, exc.message)
    return redirect('orders')


# ---------------------------------------------------------------------------
# Developer panel (staff)
# ---------------------------------------------------------------------------

@staff_member_required
def developer(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'reconcile':
                result = TransactionService().reconcile(older_than_minutes=0)
                messages.success(request, f"Checked {result['deposits']} deposit(s) and "
                                          f"{result['withdrawals']} withdrawal(s) with Paystack.")
            elif action == 'sync_banks':
                created, updated, errors = WalletService().sync_banks()
                messages.success(request, f"Banks synced: {created} new, {updated} updated, {errors} errors.")
            elif action == 'reprocess':
                from wallet.services.webhook_service import WebhookService
                ok = WebhookService().reprocess_webhook_event(request.POST.get('event_id'))
                messages.success(request, 'Event reprocessed.' if ok else 'Reprocessing failed - see the event.')
        except WalletError as exc:
            messages.error(request, exc.message)
        return redirect('developer')

    return render(request, 'shop/developer.html', {
        'events': WebhookEvent.objects.order_by('-created_at')[:25],
        'settings_rows': sorted(wallet_settings.as_dict().items()),
        'webhook_url': request.build_absolute_uri('/wallet/webhook/'),
        'callback_url': request.build_absolute_uri('/wallet/callback/'),
    })
