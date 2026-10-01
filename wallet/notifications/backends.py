"""
Notification backends.

The wallet never sends notifications by itself. Enable one or more backends::

    WALLET_NOTIFICATION_BACKENDS = [
        'wallet.notifications.backends.EmailNotificationBackend',
        'myproject.notifications.SMSBackend',
    ]

A backend receives ``(event, user, context)`` for each event below. Write your
own (SMS, push, Slack, ...) by subclassing :class:`BaseNotificationBackend`::

    class SMSBackend(BaseNotificationBackend):
        events = {'deposit_completed', 'transfer_received'}

        def send(self, event, user, context):
            sms.send(user.profile.phone, self.render_text(event, context))

Events: ``deposit_completed``, ``deposit_failed``, ``withdrawal_completed``,
``withdrawal_failed``, ``transfer_sent``, ``transfer_received``,
``payment_made``, ``payment_received``, ``payment_cancelled``,
``refund_completed``, ``refund_failed``, ``dedicated_account_assigned``,
``settlement_completed``, ``settlement_failed``, ``wallet_locked``.
"""
import logging

from django.core.mail import send_mail
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from wallet.conf import wallet_settings

logger = logging.getLogger('wallet.notifications')

SUBJECTS = {
    'deposit_completed': 'Your wallet has been funded',
    'deposit_failed': 'Your wallet funding failed',
    'withdrawal_completed': 'Your withdrawal was successful',
    'withdrawal_failed': 'Your withdrawal failed',
    'transfer_sent': 'You sent money',
    'transfer_received': 'You received money',
    'payment_made': 'Payment successful',
    'payment_received': 'You received a payment',
    'payment_cancelled': 'Payment cancelled and refunded',
    'refund_completed': 'Refund processed',
    'refund_failed': 'Refund failed',
    'dedicated_account_assigned': 'Your account number is ready',
    'settlement_completed': 'Payout completed',
    'settlement_failed': 'Payout failed',
    'wallet_locked': 'Your wallet has been locked',
}


class BaseNotificationBackend:
    #: Events this backend handles (None = all)
    events = None

    def handles(self, event):
        return self.events is None or event in self.events

    def send(self, event, user, context):
        raise NotImplementedError

    def render_text(self, event, context):
        for template in (f'wallet/notifications/{event}.txt', 'wallet/notifications/default.txt'):
            try:
                return render_to_string(template, {'event': event, **context}).strip()
            except TemplateDoesNotExist:
                continue
        return f"{event}: {context.get('amount', '')}"

    def subject(self, event, context):
        return SUBJECTS.get(event, event.replace('_', ' ').capitalize())


class LoggingNotificationBackend(BaseNotificationBackend):
    """Writes notifications to the ``wallet.notifications`` logger. Handy in development."""

    def send(self, event, user, context):
        logger.info("[notification] %s -> %s: %s", event, getattr(user, 'pk', None), self.render_text(event, context))


class EmailNotificationBackend(BaseNotificationBackend):
    """
    Sends plain-text emails with Django's email framework. Override the
    templates ``wallet/notifications/<event>.txt`` to customise the wording.
    """

    def send(self, event, user, context):
        email = getattr(user, 'email', None)
        if not email:
            return
        from django.conf import settings

        sender = wallet_settings.EMAIL_SENDER or getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        send_mail(self.subject(event, context), self.render_text(event, context), sender, [email],
                  fail_silently=False)
