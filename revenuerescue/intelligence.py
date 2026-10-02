"""Revenue Rescue intelligence primitives.

These are deterministic prioritization and classification helpers. They decide
where to spend crawl budget and which high-confidence commerce signals should
be elevated into findings.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

COMMERCIAL_URL_SIGNALS = {
    "best": 10,
    "review": 10,
    "reviews": 10,
    "comparison": 9,
    "compare": 9,
    "vs": 8,
    "deal": 8,
    "deals": 8,
    "coupon": 8,
    "discount": 8,
    "pricing": 8,
    "price": 7,
    "buy": 7,
    "shop": 6,
    "product": 6,
    "products": 6,
    "gift": 5,
    "guide": 5,
    "roundup": 7,
    "top": 6,
    "alternative": 5,
}

LOW_VALUE_URL_SIGNALS = {
    "privacy": -20,
    "terms": -20,
    "contact": -10,
    "about": -8,
    "author": -8,
    "tag": -8,
    "category": -6,
    "archive": -6,
    "page": -5,
    "login": -20,
    "account": -15,
}

TRACKING_KEYS = {
    "tag", "aff", "affid", "aff_id", "affiliate", "affiliate_id",
    "ref", "refid", "ref_id", "partner", "partner_id", "campid",
    "campaign", "subid", "sub_id", "clickid", "click_id",
}


def page_priority(url: str) -> int:
    """Score a URL for likely commercial value without fetching it."""
    parsed = urlparse(url)
    text = f"{parsed.path} {parsed.query}".lower()
    tokens = {t for t in re.split(r"[^a-z0-9]+", text) if t}
    score = 0
    for token, weight in COMMERCIAL_URL_SIGNALS.items():
        if token in tokens or f"/{token}" in parsed.path.lower():
            score += weight
    for token, weight in LOW_VALUE_URL_SIGNALS.items():
        if token in tokens:
            score += weight

    # Deep content pages tend to be more useful than home/archive URLs.
    depth = len([p for p in parsed.path.split("/") if p])
    score += min(depth, 4)

    # Common product/review slugs get a small boost.
    if re.search(r"/(dp|gp/product|products?|reviews?)/", parsed.path, re.I):
        score += 5
    return score


def tracking_params(url: str | None) -> dict[str, list[str]]:
    if not url:
        return {}
    qs = parse_qs(urlparse(url).query)
    return {k: v for k, v in qs.items() if k.lower() in TRACKING_KEYS}


def dropped_tracking_params(original_url: str, final_url: str | None) -> list[str]:
    original = tracking_params(original_url)
    final = tracking_params(final_url)
    return sorted(key for key in original if key not in final)


def discontinued_offer(commerce: dict) -> dict | None:
    """Return evidence only for explicit structured-data discontinuation.

    OutOfStock/SoldOut are intentionally NOT treated as permanent revenue leaks.
    They may be temporary inventory states. Discontinued is a stronger signal.
    """
    for offer in commerce.get("offers", []):
        availability = str(offer.get("availability", "")).lower()
        if availability.endswith("/discontinued") or availability == "discontinued":
            return {
                "availability": offer.get("availability"),
                "price": offer.get("price"),
                "currency": offer.get("currency"),
                "url": offer.get("url"),
                "seller": offer.get("seller"),
            }
    return None
