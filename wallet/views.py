"""
Paystack checkout callback.

Paystack redirects the customer to ``callback_url?reference=...&trxref=...``
after payment. Point ``WALLET_DEFAULT_CALLBACK_URL`` (or the ``callback_url``
of a deposit) at this view: it verifies the payment server-side and then
either redirects to ``WALLET_CALLBACK_REDIRECT_URL`` (your frontend) with
``?reference=...&status=...`` or renders ``wallet/payment_callback.html``.

Never credit a wallet based on the redirect alone - this view does not; it
only asks Paystack for the truth (the webhook does the same independently).
"""
import logging
from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from wallet.conf import wallet_settings
from wallet.exceptions import WalletError
from wallet.models import Transaction
from wallet.services.deposit_service import DepositService

logger = logging.getLogger('wallet')


class PaymentCallbackView(View):
    template_name = 'wallet/payment_callback.html'

    def get(self, request):
        reference = request.GET.get('reference') or request.GET.get('trxref')
        txn = None
        state = 'unknown'
        if reference:
            txn = Transaction.objects.filter(reference=reference).select_related('wallet').first()
            if txn is not None:
                try:
                    txn = DepositService().verify_deposit(reference) or txn
                    txn.refresh_from_db()
                except WalletError as exc:
                    logger.warning("Callback verification failed for %s: %s", reference, exc)
                state = txn.status

        redirect_to = wallet_settings.CALLBACK_REDIRECT_URL
        if redirect_to:
            separator = '&' if '?' in redirect_to else '?'
            return HttpResponseRedirect(f"{redirect_to}{separator}{urlencode({'reference': reference or '', 'status': state})}")

        return render(request, self.template_name, {'transaction': txn, 'reference': reference, 'status': state},
                      status=200 if txn is not None else 404)


# Backwards compatible name
SuccessPageView = PaymentCallbackView
