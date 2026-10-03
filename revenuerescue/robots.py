#!/usr/bin/env python3
"""robots.txt enforcement for the Revenue Rescue crawler.

Minimal RFC 9309 implementation, stdlib only:
- per-host fetch of /robots.txt, cached in memory
  (1h for successful parses, 5min for fetch failures)
- group selection: most-specific user-agent prefix match, else "*" groups
- path matching with * wildcards and $ end-anchors; longest-match-wins
  between Allow and Disallow

Failure semantics: robots.txt unreachable -> ALLOW + log. We obey explicit
Disallow rules; we never fail closed on infrastructure hiccups. Callers skip
disallowed URLs with an inconclusive verdict -- never a finding -- consistent
with the honest-verdict engine (excluded/blocked != broken).

Our fetcher sends a browser-style User-Agent (see audit.UA), so group
matching is done by case-insensitive prefix against that string, falling
back to the "*" catch-all groups. In practice the "*" group governs.
"""

import logging
import re
import time
from urllib.parse import urlparse

logger = logging.getLogger("revenuerescue")

ROBOTS_TTL = 3600       # cache successful parses for 1h
ROBOTS_FAIL_TTL = 300   # cache fetch failures briefly to avoid hammering
MAX_ROBOTS_BYTES = 512 * 1024

# host -> (expires_at, rules). rules is a list of (is_allow, pattern).
_cache = {}


def _default_ua():
    # Deferred import: audit.py imports this module at load time.
    from .audit import UA
    return UA["User-Agent"]


def _default_fetcher(scheme, netloc):
    """Fetch scheme://netloc/robots.txt via the SSRF-guarded fetcher.

    Returns the body text, or None when unavailable (network error,
    non-200, oversize). Never raises.
    """
    from .security import safe_get
    from .audit import UA
    target = f"{scheme}://{netloc}/robots.txt"
    try:
        r = safe_get(target, headers=UA, timeout=10)
        try:
            if r.status_code != 200:
                logger.info("robots.txt: %s -> HTTP %s; allowing", target,
                            r.status_code)
                return None
            length = r.headers.get("Content-Length")
            if length and int(length) > MAX_ROBOTS_BYTES:
                logger.info("robots.txt: %s oversize (%s bytes); allowing",
                            target, length)
                return None
            return r.text
        finally:
            r.close()
    except Exception as e:
        logger.info("robots.txt: fetch failed for %s: %s; allowing",
                    target, type(e).__name__)
        return None


def parse_robots_txt(text):
    """Parse robots.txt into [(agents, [(is_allow, pattern), ...]), ...].

    Consecutive User-agent lines form one group. Comments (#) stripped.
    Unknown directives ignored.
    """
    groups = []
    cur_agents, cur_rules = [], []

    def flush():
        if cur_agents or cur_rules:
            groups.append((cur_agents, cur_rules))

    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if cur_rules:
                # Rules already seen: previous group is complete.
                groups.append((cur_agents, cur_rules))
                cur_agents, cur_rules = [], []
            cur_agents.append(value.lower())
        elif field in ("allow", "disallow"):
            if not cur_agents:
                continue  # rules before any User-agent line: ignore
            cur_rules.append((field == "allow", value))
    flush()
    return groups


def _select_rules(groups, ua):
    """Return the rules of the most-specific matching group.

    A group matches when one of its agent tokens is a case-insensitive
    prefix of our user-agent string. Longest matching token wins. Falls
    back to the combined "*" groups. No match anywhere -> [] (allow all).
    """
    ua_l = ua.lower()
    best_rules, best_len = None, -1
    for agents, rules in groups:
        for agent in agents:
            if agent == "*":
                continue
            if agent and ua_l.startswith(agent) and len(agent) > best_len:
                best_rules, best_len = rules, len(agent)
    if best_rules is not None:
        return best_rules
    wild = []
    for agents, rules in groups:
        if any(a == "*" for a in agents):
            wild.extend(rules)
    return wild


def _pattern_regex(pattern):
    # RFC 9309: * matches any sequence, $ anchors the end.
    out = []
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        elif ch == "$":
            out.append("$")
        else:
            out.append(re.escape(ch))
    return re.compile("".join(out))


def _path_matches(pattern, path_query):
    if not pattern:
        return False  # empty Disallow = allow all
    return _pattern_regex(pattern).match(path_query) is not None


def _rules_for_host(host_key, scheme, netloc, ua, fetcher):
    now = time.time()
    hit = _cache.get(host_key)
    if hit and hit[0] > now:
        return hit[1]
    fetch = fetcher or (lambda _host: _default_fetcher(scheme, netloc))
    try:
        text = fetch(host_key)
    except Exception as e:  # a custom fetcher misbehaving: allow + log
        logger.info("robots.txt: fetcher error for %s: %s; allowing",
                    host_key, type(e).__name__)
        text = None
    if text is None:
        _cache[host_key] = (now + ROBOTS_FAIL_TTL, [])
        return []
    try:
        rules = _select_rules(parse_robots_txt(text), ua)
    except Exception as e:
        logger.info("robots.txt: parse error for %s: %s; allowing",
                    host_key, type(e).__name__)
        rules = []
    _cache[host_key] = (now + ROBOTS_TTL, rules)
    return rules


def clear_cache():
    """Drop the per-host robots cache (used by tests)."""
    _cache.clear()


def is_allowed(url, user_agent=None, fetcher=None):
    """True if fetching `url` is permitted by the host's robots.txt.

    Total function: never raises -- any internal problem allows the fetch
    and logs, so robots handling can never break an audit.
    `fetcher` is an injectable `host -> text|None` for tests.
    """
    try:
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if not host or parts.scheme not in ("http", "https"):
            return True
        ua = user_agent or _default_ua()
        # Cache key keeps the port: robots.txt is per scheme+host+port.
        host_key = parts.netloc.lower()
        rules = _rules_for_host(host_key, parts.scheme, parts.netloc, ua,
                                fetcher)
        if not rules:
            return True
        path_query = parts.path or "/"
        if parts.query:
            path_query += "?" + parts.query
        best_len, best_allow = -1, True
        for allow_flag, pattern in rules:
            if not pattern:
                continue
            if _path_matches(pattern, path_query) and len(pattern) > best_len:
                best_len, best_allow = len(pattern), allow_flag
        return best_allow
    except Exception as e:  # never let robots handling break a fetch
        logger.info("robots.txt: check failed for %s: %s; allowing",
                    url, type(e).__name__)
        return True
