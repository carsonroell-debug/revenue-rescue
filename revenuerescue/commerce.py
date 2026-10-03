"""Commerce context extraction from publisher/store pages.

This is deterministic structured-data extraction, not LLM inference. The goal
is to give Revenue Rescue enough context to rank a broken destination by its
commercial importance without inventing revenue estimates.
"""
from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup


def _iter_nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nodes(child)


def _types(node: dict) -> set[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, list):
        return {str(v).lower() for v in value}
    return set()


def extract_commerce_context(soup: BeautifulSoup) -> dict:
    products: list[dict] = []
    offers: list[dict] = []

    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        for node in _iter_nodes(payload):
            node_types = _types(node)
            if "product" in node_types:
                item = {
                    "name": node.get("name"),
                    "sku": node.get("sku"),
                    "brand": (
                        node.get("brand", {}).get("name")
                        if isinstance(node.get("brand"), dict)
                        else node.get("brand")
                    ),
                    "url": node.get("url"),
                }
                products.append({k: v for k, v in item.items() if v not in (None, "")})

            if "offer" in node_types or "aggregateoffer" in node_types:
                item = {
                    "price": node.get("price") or node.get("lowPrice"),
                    "high_price": node.get("highPrice"),
                    "currency": node.get("priceCurrency"),
                    "availability": node.get("availability"),
                    "url": node.get("url"),
                    "seller": (
                        node.get("seller", {}).get("name")
                        if isinstance(node.get("seller"), dict)
                        else node.get("seller")
                    ),
                }
                offers.append({k: v for k, v in item.items() if v not in (None, "")})

    # Common OpenGraph/product meta fallbacks.
    meta = {}
    for key in (
        "product:price:amount",
        "product:price:currency",
        "og:price:amount",
        "og:price:currency",
    ):
        el = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if el and el.get("content"):
            meta[key] = el.get("content")

    return {
        "has_product_schema": bool(products),
        "has_offer_schema": bool(offers),
        "products": products[:20],
        "offers": offers[:20],
        "meta": meta,
    }
