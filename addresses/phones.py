"""UK mobile number normalisation.

`Address.phone` is a plain CharField with no validators, no `clean()` and no
normalisation, so numbers are stored exactly as the customer typed them
("07700 900123", "+44 7700 900123", "00447700900123", ...). Anything that
counts or exports them has to parse them first.

Kept free of Django imports so it can be unit-tested without a database.
"""
import re

# ^\+447 plus nine more digits is the shape of every UK mobile in E.164.
_UK_MOBILE = re.compile(r'^\+447\d{9}$')


def normalise_uk_mobile(raw):
    """Return a UK mobile as E.164 ('+447700900123'), or None.

    None means "not a UK mobile we can text": blank, a landline, an
    international number, or junk.
    """
    if raw is None:
        return None

    text = str(raw).strip()
    if not text:
        return None

    had_plus = text.startswith('+')
    digits = re.sub(r'\D', '', text)
    if not digits:
        return None

    if had_plus or digits.startswith('00'):
        # Already international; strip the 00 trunk prefix if that is how it
        # was written. A non-UK country code simply fails the check below.
        if digits.startswith('00'):
            digits = digits[2:]
    elif digits.startswith('0'):
        # National form: 07700 900123
        digits = '44' + digits[1:]
    elif not digits.startswith('44'):
        # Bare national number with the trunk 0 omitted: 7700900123
        digits = '44' + digits

    candidate = '+' + digits
    if not _UK_MOBILE.match(candidate):
        return None

    # Not every 07 range is a mobile. 070 is personal numbering and 076 is
    # pagers - except 07624, which is Isle of Man mobile. Treating all of 07 as
    # mobile over-counts the list and inflates the SMS spend.
    if candidate.startswith('+4470'):
        return None
    if candidate.startswith('+4476') and not candidate.startswith('+447624'):
        return None

    return candidate


def split_name(first_name, last_name, full_name):
    """Best-effort (first, last) for the Mailchimp columns.

    Address has first_name/last_name/full_name and all three are nullable, so
    fall back to splitting full_name when the structured pair is missing.
    """
    first = (first_name or '').strip()
    last = (last_name or '').strip()
    if first or last:
        return first, last

    whole = (full_name or '').strip()
    if not whole:
        return '', ''
    parts = whole.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else '')
