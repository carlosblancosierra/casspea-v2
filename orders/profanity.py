"""Keep rude words out of the random part of order IDs.

The random part is five characters from ORDER_ID_CHARS. That alphabet has no
I, O, 0 or 1, so any word needing an I or an O can never come out, and this
list only carries words that can. Digits are read as the letters they look
like (4 -> A, 5 -> S, ...) so "F4G5" counts as "FAGS". A code is rejected if
any listed word appears anywhere in it, so a short word also catches every
code that contains it ("XFAGX", "PUTAB").

A rejected code costs nothing: generate_order_id just draws another one.
False positives are cheap; a false negative ends up on a customer's receipt.
"""

ORDER_ID_CHARS = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'

# How a digit reads to someone looking at it. 0 and 1 are not in the
# alphabet, so they are not here.
LOOKALIKES = str.maketrans({
    '2': 'Z',
    '3': 'E',
    '4': 'A',
    '5': 'S',
    '6': 'G',
    '7': 'T',
    '8': 'B',
    '9': 'G',
})

BLOCKED_WORDS = frozenset({
    # English
    'ANAL', 'ANUS', 'ARSE', 'ASS', 'BUTT', 'CRAP', 'CUM', 'CUNT', 'DAMN',
    'DYKE', 'FAG', 'FCK', 'FUC', 'FUK', 'FVCK', 'KKK', 'KUNT', 'MUFF',
    'NGGA', 'NGGR', 'NUDE', 'PEE', 'PUKE', 'RAPE', 'RTRD', 'SCAT', 'SEX',
    'PUSSY', 'SHAG', 'SKANK', 'SLAG', 'SLUT', 'SMEG', 'SPAC', 'SPAZ',
    'SPERM', 'STD', 'SUCK', 'TARD', 'TURD', 'TWAT', 'WANK', 'WTF', 'XXX',
    # Spanish
    'CACA', 'CAGA', 'CTM', 'HDP', 'LPM', 'MEAR', 'MRD', 'PAJA', 'PENE',
    'PERRA', 'PNDJ', 'PTA', 'PTM', 'PUTA', 'PUTE', 'PUTX', 'TETA', 'VERGA',
    'VRG',
    # Other European languages a UK customer may read
    'ARSCH', 'CAZZ', 'CUL', 'MERDE', 'MRDE',
    # Numbers, checked as typed rather than as letters
    '666', '69',
})


def is_offensive(code):
    """True if the code spells, or contains, a blocked word."""
    code = code.upper()
    readings = {code, code.translate(LOOKALIKES)}
    return any(
        word in reading
        for reading in readings
        for word in BLOCKED_WORDS
    )
