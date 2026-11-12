"""The unsubscribe link at the bottom of every email.

Each email carries a link to the storefront's /unsubscribe page with a signed
token for its recipient. The page posts the token back to
POST /api/leads/unsubscribe/, which records the opt-out. The token is signed
with SECRET_KEY, so nobody can unsubscribe an address they cannot read the
email of, and it does not expire: an old email's link must keep working.
"""
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.db.models.functions import Lower

from .models import EmailOptOut, Lead

SALT = 'leads.unsubscribe'


def normalise(email):
    return (email or '').strip().lower()


def unsubscribe_token(email):
    return signing.dumps(normalise(email), salt=SALT)


def email_from_token(token):
    """The address a token was made for. Raises signing.BadSignature."""
    email = signing.loads(token, salt=SALT)
    if not isinstance(email, str) or '@' not in email:
        raise signing.BadSignature('Not an unsubscribe token')
    return email


def unsubscribe_url(email):
    """Link for the footer of an email to `email`."""
    return f"{settings.SITE_URL}/unsubscribe?token={quote(unsubscribe_token(email))}"


def opt_out(email):
    email = normalise(email)
    EmailOptOut.objects.get_or_create(email=email)
    Lead.objects.filter(email__iexact=email).update(unsubscribed=True)
    return email


def is_opted_out(email):
    return EmailOptOut.objects.filter(email=normalise(email)).exists()


def opted_out_emails():
    """Subquery of every opted-out address, for excluding recipients."""
    return EmailOptOut.objects.values('email')


def exclude_opted_out(queryset, *email_fields):
    """`queryset` without rows whose address, in any of `email_fields`
    (compared case-insensitively), has opted out."""
    for i, field in enumerate(email_fields):
        alias = f'_optout_email_{i}'
        # "IS NOT NULL" keeps rows where this field is empty (a guest order
        # has no user email): in SQL, NULL IN (...) is NULL, and excluding
        # on NULL alone would drop them.
        queryset = queryset.annotate(**{alias: Lower(field)}).exclude(
            **{f'{alias}__in': opted_out_emails(), f'{alias}__isnull': False}
        )
    return queryset


def mask(email):
    """a•••@example.com: enough for someone to recognise their own address."""
    local, _, domain = email.partition('@')
    return f"{local[:1]}•••@{domain}"

