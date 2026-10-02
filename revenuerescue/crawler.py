"""Crawlee-powered orchestration for Revenue Rescue page fetches.

Crawlee coordinates a prevalidated request set, concurrency, retries, and
resource-aware scaling. It does NOT own network policy: callers inject the
Revenue Rescue fetcher, which already performs SSRF validation and Scrapling
escalation. This preserves the core safety invariant while gaining production
crawl orchestration.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Any

from crawlee import ConcurrencySettings
from crawlee.crawlers import BasicCrawler, BasicCrawlingContext

from .security import validate_public_http_url

Fetcher = Callable[[str], Any]


async def crawl_pages(
    urls: list[str],
    fetcher: Fetcher,
    *,
    max_concurrency: int = 4,
    max_tasks_per_minute: int = 90,
) -> list[dict]:
    """Fetch a bounded list of public pages concurrently with Crawlee.

    The injected fetcher is responsible for redirects, SSRF safety, bot-wall
    handling, and browser/stealth escalation. Crawlee only schedules work.
    """
    safe_urls: list[str] = []
    seen: set[str] = set()
    for url in urls:
        validate_public_http_url(url)
        if url not in seen:
            seen.add(url)
            safe_urls.append(url)

    results: dict[str, dict] = {}

    crawler = BasicCrawler(
        max_requests_per_crawl=len(safe_urls) or 1,
        max_request_retries=2,
        concurrency_settings=ConcurrencySettings(
            min_concurrency=1,
            desired_concurrency=min(2, max_concurrency),
            max_concurrency=max_concurrency,
            max_tasks_per_minute=max_tasks_per_minute,
        ),
        abort_on_error=False,
        configure_logging=False,
    )

    @crawler.router.default_handler
    async def handler(context: BasicCrawlingContext) -> None:
        url = context.request.url
        response = await asyncio.to_thread(fetcher, url)
        results[url] = {
            "page": url,
            "status": getattr(response, "status_code", None),
            "final_url": getattr(response, "url", url),
            "html": getattr(response, "text", "") or "",
            "fetch_tier": getattr(response, "fetch_tier", "http"),
            "error": None,
        }

    @crawler.failed_request_handler
    async def failed(context: BasicCrawlingContext, error: Exception) -> None:
        url = context.request.url
        results[url] = {
            "page": url,
            "status": None,
            "final_url": None,
            "html": "",
            "fetch_tier": None,
            "error": f"{type(error).__name__}: {error}",
        }

    if safe_urls:
        await crawler.run(safe_urls)
    return [results.get(url, {
        "page": url,
        "status": None,
        "final_url": None,
        "html": "",
        "fetch_tier": None,
        "error": "crawler produced no result",
    }) for url in safe_urls]


def crawl_pages_sync(
    urls: list[str],
    fetcher: Fetcher,
    *,
    max_concurrency: int = 4,
    max_tasks_per_minute: int = 90,
) -> list[dict]:
    """Synchronous bridge for the existing audit engine and worker threads."""
    return asyncio.run(
        crawl_pages(
            urls,
            fetcher,
            max_concurrency=max_concurrency,
            max_tasks_per_minute=max_tasks_per_minute,
        )
    )
