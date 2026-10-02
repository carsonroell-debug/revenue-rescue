"""Network safety for public-site crawling.

Revenue Rescue accepts user-supplied domains, so every outbound crawl target
must be constrained to public HTTP(S) destinations. This module blocks obvious
SSRF targets before requests and before every redirect hop.

Production deployments should ALSO use an egress firewall / network policy.
Application-layer validation is defense in depth, not a substitute for network
isolation against DNS rebinding.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


class UnsafeTarget(ValueError):
    """Raised when a requested crawl target is not a public HTTP(S) address."""


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return bool(ip.is_global)


def validate_public_http_url(url: str) -> str:
    """Validate that URL resolves only to globally routable addresses."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeTarget("only http:// and https:// URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeTarget("URLs containing credentials are not allowed")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeTarget("URL must include a hostname")
    if host in BLOCKED_HOSTNAMES or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeTarget("private/local hostnames are not allowed")

    # IP literals are validated directly; hostnames must resolve exclusively to
    # public addresses. If DNS cannot resolve, let the normal request path
    # surface the connectivity failure rather than treating it as a leak.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror:
            return url
        addresses = {info[4][0] for info in infos}
        if any(not _is_public_ip(address) for address in addresses):
            raise UnsafeTarget("hostname resolves to a non-public IP address")
    else:
        if not _is_public_ip(host):
            raise UnsafeTarget("non-public IP addresses are not allowed")
    return url


def safe_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 20,
    stream: bool = False,
    max_redirects: int = 8,
) -> requests.Response:
    """GET a public URL while validating each redirect destination.

    Redirects are followed manually so a public URL cannot trivially bounce the
    crawler into localhost, RFC1918, link-local, or metadata addresses.
    """
    current = validate_public_http_url(url)
    history: list[requests.Response] = []
    session = requests.Session()

    for _ in range(max_redirects + 1):
        response = session.get(
            current,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=stream,
        )
        if response.status_code not in REDIRECT_STATUSES:
            response.history = history
            return response

        location = response.headers.get("location")
        if not location:
            response.history = history
            return response

        target = urljoin(current, location)
        validate_public_http_url(target)
        response.close()
        history.append(response)
        current = target

    raise requests.TooManyRedirects(f"more than {max_redirects} redirects for {url}")
