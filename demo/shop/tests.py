"""
Demo smoke tests:  cd demo && python manage.py test shop
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from shop.models import Order, Product
from wallet.models import Transaction, Wallet
from wallet.services import WalletService


@override_settings(PAYSTACK_SECRET_KEY='sk_test_demo', PAYSTACK_PUBLIC_KEY='pk_test_demo',
                   WALLET_AUTO_CREATE_PAYSTACK_CUSTOMER=False, WALLET_ENABLE_FEES=True,
                   WALLET_ENABLE_PAYMENT_FEES=True, WALLET_PAYMENT_PERCENTAGE_FEE=5,
                   WALLET_PAYMENT_FEE_BEARER='merchant', WALLET_REQUIRE_TRANSACTION_PIN=False)
class DemoTests(TestCase):

    def setUp(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command('seed_demo', '--no-banks', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.ada = get_user_model().objects.get(username='ada')
        self.seller = get_user_model().objects.get(username='seller')
        self.client.force_login(self.ada)

    def balance(self, user):
        return Wallet.objects.get(user=user).balance.amount

    def test_seed_is_idempotent(self):
        call_command('seed_demo', '--no-banks', stdout=mock.MagicMock())
        self.assertEqual(self.balance(self.ada), Decimal('50000'))
        self.assertEqual(Product.objects.count(), 3)

    def test_every_page_renders(self):
        for name in ('dashboard', 'send', 'withdraw', 'cards', 'history', 'shop', 'orders'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertIn('csrftoken', response.cookies, name)
        self.assertEqual(self.client.get(reverse('developer')).status_code, 302)   # staff only
        self.client.force_login(get_user_model().objects.get(username='admin'))
        self.assertEqual(self.client.get(reverse('developer')).status_code, 200)

    def test_signup_creates_wallet_with_phone(self):
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('signup'), {
                'username': 'chi', 'email': 'chi@example.com', 'first_name': 'Chi', 'last_name': 'Eze',
                'phone_number': '0804 444 4444', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123',
            })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(Wallet.objects.get(user__username='chi').phone_number, '+2348044444444')

    def test_buy_confirm_and_seller_gets_paid_minus_commission(self):
        product = Product.objects.get(name='Ankara tote bag')        # NGN 7,500
        self.client.post(reverse('buy', args=[product.pk]))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.STATUS_IN_ESCROW)
        self.assertEqual(self.balance(self.ada), Decimal('42500'))
        self.assertEqual(self.balance(self.seller), Decimal('0'))

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('confirm-delivery', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_COMPLETED)          # via the payment_released signal
        self.assertEqual(self.balance(self.seller), Decimal('7125'))    # 5% commission

    def test_seller_refund(self):
        product = Product.objects.get(name='Phone case')
        self.client.post(reverse('buy', args=[product.pk]))
        order = Order.objects.get()
        self.client.force_login(self.seller)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('refund-order', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_REFUNDED)
        self.assertEqual(self.balance(self.ada), Decimal('50000'))

    def test_escrow_released_by_staff_through_the_api_updates_the_order(self):
        product = Product.objects.get(name='Phone case')
        self.client.post(reverse('buy', args=[product.pk]))
        order = Order.objects.get()
        self.client.force_login(get_user_model().objects.get(username='admin'))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'/wallet/api/transactions/{order.payment_id}/release/')
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_COMPLETED)

    def test_cannot_buy_own_product_or_overspend(self):
        self.client.force_login(self.seller)
        product = Product.objects.first()
        self.client.post(reverse('buy', args=[product.pk]))
        self.assertFalse(Order.objects.exists())
        self.client.force_login(self.ada)
        expensive = Product.objects.create(seller=self.seller, name='Car', price=Decimal('9000000'))
        response = self.client.post(reverse('buy', args=[expensive.pk]), follow=True)
        self.assertContains(response, 'Insufficient funds')
        self.assertFalse(Order.objects.exists())

    @override_settings(WALLET_REQUIRE_TRANSACTION_PIN=True)
    def test_pin_required_for_shop_purchases(self):
        product = Product.objects.get(name='Phone case')
        response = self.client.post(reverse('buy', args=[product.pk]), follow=True)
        self.assertContains(response, 'PIN is required')
        wallet = Wallet.objects.get(user=self.ada)
        wallet.set_pin('4826')
        self.client.post(reverse('buy', args=[product.pk]), {'pin': '4826'})
        self.assertEqual(Order.objects.count(), 1)

    def test_sell(self):
        self.client.post(reverse('sell'), {'name': 'Mug', 'price': '1200'})
        self.assertTrue(Product.objects.filter(name='Mug', seller=self.ada).exists())
        self.client.post(reverse('sell'), {'name': '', 'price': 'abc'})
        self.assertEqual(Product.objects.filter(seller=self.ada).count(), 1)

    def test_transfer_by_phone_through_the_api_like_the_send_page(self):
        response = self.client.post('/wallet/api/wallets/me/transfer/',
                                    {'recipient': '0803 222 2222', 'amount': '1500'},
                                    content_type='application/json', HTTP_IDEMPOTENCY_KEY='demo-1')
        self.assertEqual(response.status_code, 201)
        replay = self.client.post('/wallet/api/wallets/me/transfer/',
                                  {'recipient': '0803 222 2222', 'amount': '1500'},
                                  content_type='application/json', HTTP_IDEMPOTENCY_KEY='demo-1')
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(self.balance(get_user_model().objects.get(username='bola')), Decimal('51500'))

    def test_callback_redirects_to_dashboard_with_status(self):
        wallet = WalletService().get_wallet(self.ada)
        txn = Transaction.objects.create(wallet=wallet, amount=Decimal('100'), transaction_type='deposit',
                                         reference='DEP-DEMO-1')
        with mock.patch('wallet.services.deposit_service.DepositService.verify_deposit', return_value=txn), \
                override_settings(WALLET_CALLBACK_REDIRECT_URL='/'):
            response = self.client.get('/wallet/callback/', {'reference': 'DEP-DEMO-1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/?reference=DEP-DEMO-1&status=pending')

    def test_developer_tools(self):
        self.client.force_login(get_user_model().objects.get(username='admin'))
        response = self.client.post(reverse('developer'), {'action': 'reconcile'}, follow=True)
        self.assertContains(response, 'Checked 0 deposit(s)')
        with mock.patch('wallet.services.wallet_service.WalletService.sync_banks', return_value=(3, 0, 0)):
            response = self.client.post(reverse('developer'), {'action': 'sync_banks'}, follow=True)
        self.assertContains(response, 'Banks synced: 3 new')
