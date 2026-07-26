"""Helpers for the time-gated Summer Break store closure.

A single source of truth (``settings.STORE_ORDER_DEADLINE``) decides whether the
shop is still accepting orders. The Stripe checkout views call ``store_is_open``
before creating a session, and the ``/api/checkout/store-status/`` endpoint
exposes the same decision to the frontend so the UI and the API can never drift.
"""
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def get_order_deadline():
    """Return the configured deadline as a timezone-aware datetime, or None."""
    raw = getattr(settings, 'STORE_ORDER_DEADLINE', '') or ''
    if not raw:
        return None
    deadline = parse_datetime(raw)
    if deadline is None:
        return None
    if timezone.is_naive(deadline):
        deadline = timezone.make_aware(deadline, timezone.get_default_timezone())
    return deadline


def store_is_open(now=None):
    """True if the shop is still accepting orders."""
    deadline = get_order_deadline()
    if deadline is None:
        return True
    return (now or timezone.now()) <= deadline


def store_status():
    """Serializable status dict for the frontend."""
    deadline = get_order_deadline()
    return {
        'open': store_is_open(),
        'deadline': deadline.isoformat() if deadline else None,
        'reopen_label': getattr(settings, 'STORE_REOPEN_LABEL', ''),
    }
