import re

# Crawlers are a large, uneven share of product-page traffic and they never
# buy. Left in the denominator they drag both conversion rates towards zero
# and, because crawl volume is not evenly split, they can move the arms by
# different amounts.
BOT_PATTERN = re.compile(
    r'bot|crawler|spider|crawling|slurp|bingpreview|facebookexternalhit|'
    r'headlesschrome|phantomjs|lighthouse|pingdom|uptimerobot|curl|wget|python-requests',
    re.IGNORECASE,
)


def is_bot(request) -> bool:
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    if not user_agent:
        # No UA at all is not a browser a customer is using.
        return True
    return bool(BOT_PATTERN.search(user_agent))
