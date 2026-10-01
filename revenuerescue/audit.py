#!/usr/bin/env python3
"""Revenue Rescue audit engine: discover review pages, extract outbound
affiliate/merchant links, verify each destination (status, redirect chain,
tracking params).

Hardened from the LinkRescue linkscan.py prototype. Caveats applied verbatim
from operational notes (see connector README, "Scanner caveats"):
 1. Geniuslink/Skimlinks-style proxy links attach the affiliate tag server-side,
    so any "missing tag" style verdict on them is a false positive -> treated as
    unverified, never reported as findings (unless the destination itself is dead).
 2. bot-blocked / timeout / connection-failed is NOT a broken link. A finding is
    only reported when a plain re-fetch confirms the destination is actually dead
    (404/410/5xx or soft-404 redirects). Everything else is inconclusive.
 3. is_affiliate() covers creator shorteners incl. lvnta.com (Levanta's Amazon
    shortener, tag=maas).
 4. Content extraction is theme-aware: first-<article> matching fails silently on
    Divi-theme sites (hits related-post cards), so we strip nav/footer/sidebars/
    related blocks and pick the real content container, with a Divi-specific path.
 5. pick_pages() falls back to web-search-discovered review URLs when WordPress
    sitemaps are slow or unreachable.
 6. All intermediates live in the project's work/ dir, never /tmp.

Engine only: no agent-platform concepts here. Agent adapters live in
revenuerescue/adapters/ and translate platform invocations into these calls.
"""
import json
import re
import sys
import time
import random
import html as ihtml
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml"}

BASE_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = BASE_DIR / "work"
WORK_DIR.mkdir(parents=True, exist_ok=True)

AFFILIATE_PATTERNS = [
    r"amzn\.to", r"amazon\.", r"go\.skimresources\.com", r"skimlinks",
    r"avantlink", r"anrdoezrs\.net", r"jdoqocy\.com", r"shareasale\.com",
    r"shrsl\.com", r"impactradius", r"\.impact\.com", r"pxf\.io", r"sjv\.io",
    r"rover\.ebay\.com", r"linksynergy\.com", r"partnerize", r"awin",
    r"clk\.tradetracker", r"snp\.link",
    r"lvnta\.com",          # Levanta's Amazon affiliate shortener (tag=maas)
    r"geni\.us", r"geniuslink",  # creator link shorteners
]
AFF_RE = re.compile("|".join(AFFILIATE_PATTERNS), re.I)
AMAZON_RE = re.compile(r"amazon\.", re.I)

# Proxy-style affiliate links that attach the tracking tag SERVER-SIDE.
# Any "missing tag/attribution" verdict on these is a false positive by
# construction: they never carry the tag in the visible URL.
PROXY_RE = re.compile(
    r"go\.skimresources\.com|skimlinks|geni\.us|geniuslink", re.I)

# share widgets / non-content links: never findings
SHARE_RE = re.compile(
    r"linkedin\.com/shareArticle|twitter\.com/intent|facebook\.com/sharer|"
    r"pinterest\.com/pin/create|whatsapp\.com|telegram\.me/share|"
    r"mailto:|/cdn-cgi/", re.I)

REVIEW_HINTS = ["review", "best-", "best_", "/best/", "vs-", "-vs-", "versus",
                "guide", "roundup", "round-up", "top-", "comparison", "hands-on",
                "tested", "alternative"]

# hosts known to block datacenter IPs; connection failures there are inconclusive
BOTWALL = ["rei.com", "www.rei.com", "backcountry.com", "www.backcountry.com",
           "moosejaw.com", "www.moosejaw.com"]

PRODUCT_HINT = re.compile(r"/(products|dp|gp/product|itm|p/|product)/", re.I)
CATEGORY_HINT = re.compile(r"/(collections|category|categories|shop|sitemap|search|c/)/", re.I)

# boilerplate selectors stripped before content extraction (Divi-aware)
STRIP_SELECTORS = [
    "nav", "footer", "aside", "header",
    "[class*='sidebar']", "[class*='widget-area']", "[class*='widget_area']",
    "[class*='related']", "[class*='comment']", "[id*='comment']",
    "[class*='et_pb_widget_area']", "[class*='et_pb_sidebar']",
    "[class*='share-buttons']", "[class*='social-share']",
]


def fetch(url, timeout=20, tries=3):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
            return r
        except Exception as e:
            last = e
            time.sleep(1 + i * 2)
    raise last


def sitemap_urls(base):
    out = []
    try:
        r = fetch(base.rstrip("/") + "/sitemap.xml")
        if r.status_code != 200:
            return out
        root = ET.fromstring(r.content)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        smaps = root.findall("s:sitemap", ns)
        targets = []
        if smaps:
            for s in smaps[:8]:
                loc = s.find("s:loc", ns)
                if loc is not None and loc.text:
                    targets.append(loc.text.strip())
        else:
            targets = [base.rstrip("/") + "/sitemap.xml"]
        for t in targets:
            try:
                rr = fetch(t)
                if rr.status_code != 200:
                    continue
                rt = ET.fromstring(rr.content)
                for u in rt.findall("s:url", ns):
                    loc = u.find("s:loc", ns)
                    lm = u.find("s:lastmod", ns)
                    if loc is not None and loc.text:
                        out.append((loc.text.strip(),
                                    lm.text.strip() if lm is not None and lm.text else ""))
            except Exception:
                continue
    except Exception:
        pass
    return out


def websearch_review_urls(base, n=8):
    """Fallback: discover likely review pages via web search when the sitemap
    is slow or unreachable. DuckDuckGo HTML endpoint, no API key needed."""
    host = urlparse(base).netloc
    urls = []
    try:
        q = f"site:{host} review"
        r = requests.get("https://html.duckduckgo.com/html/",
                         params={"q": q}, headers=UA, timeout=20)
        if r.status_code != 200:
            return urls
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = unquote(m.group(1))
            if host in urlparse(href).netloc and href not in urls:
                urls.append(href)
            if len(urls) >= n:
                break
    except Exception:
        pass
    return urls


def pick_pages(base, n=8):
    urls = sitemap_urls(base)
    if not urls:
        # slow/unreachable WordPress sitemap -> web-search fallback
        return websearch_review_urls(base, n) or []
    hinted, rest = [], []
    for loc, lm in urls:
        low = loc.lower()
        if any(x in low for x in ["/tag/", "/category/", "/author/", "/page/",
                                 "/product-tag", "/product_cat", "#"]):
            continue
        if "sitemap" in low:
            continue
        if any(h in low for h in REVIEW_HINTS):
            hinted.append((lm or "9999", loc))
        else:
            rest.append((lm or "9999", loc))
    hinted.sort()
    rest.sort()
    pages = [loc for _, loc in hinted[:n]]
    if len(pages) < n:
        pages += [loc for _, loc in rest[: n - len(pages)]]
    if not pages:
        pages = websearch_review_urls(base, n)
    return pages


def _strip_boilerplate(soup):
    for sel in STRIP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    return soup


def main_content(soup):
    """Theme-aware content extraction. First-<article> matching fails silently
    on Divi sites (matches related-post cards), so: detect Divi and prefer its
    real post container; otherwise pick the largest article/main candidate after
    boilerplate removal."""
    html_text = str(soup)[:200000]
    is_divi = "et_pb_" in html_text or "Divi" in html_text
    if is_divi:
        post = soup.select_one(".et_pb_post_content")
        if post and len(post.get_text(strip=True)) > 300:
            return post
    candidates = []
    for sel in ["article", "main", "div[role='main']", ".entry-content",
                ".post-content", ".article-content"]:
        for el in soup.select(sel):
            txt = el.get_text(strip=True)
            if len(txt) > 300:
                candidates.append((len(txt), el))
    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]
    return soup.body or soup


def extract_links(page_url, base_host):
    try:
        r = fetch(page_url)
    except Exception as e:
        return [], f"page fetch failed: {type(e).__name__}"
    if r.status_code != 200:
        return [], f"page returned {r.status_code}"
    soup = BeautifulSoup(r.text, "html.parser")
    soup = _strip_boilerplate(soup)
    content = main_content(soup)
    links, seen = [], set()
    for a in content.find_all("a", href=True):
        h = ihtml.unescape(a["href"]).strip()
        if not h or h.startswith(("#", "tel:", "javascript:")):
            continue
        absu = urljoin(page_url, h)
        if SHARE_RE.search(absu):
            continue
        p = urlparse(absu)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower() == base_host.lower():
            continue
        if absu in seen:
            continue
        seen.add(absu)
        links.append(absu)
    return links, None


def check_link(url, tries=3):
    chain, last_err = [], None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=20, allow_redirects=True, stream=True)
            for h in r.history:
                chain.append({"status": h.status_code, "url": h.url})
            res = {"url": url, "chain": chain, "final_status": r.status_code,
                   "final_url": r.url, "error": None}
            r.close()
            return res
        except Exception as e:
            last_err = f"{type(e).__name__}"
            chain = []
            time.sleep(1 + i * 2)
    return {"url": url, "chain": [], "final_status": None, "final_url": None,
            "error": f"connection failed x{tries} ({last_err})"}


def is_affiliate(url):
    return bool(AFF_RE.search(url))


def is_proxy(url):
    """True for Geniuslink/Skimlinks-style proxy links that attach the tag
    server-side. Attribution verdicts on these are false positives."""
    return bool(PROXY_RE.search(url))


def botwalled(url):
    return urlparse(url).netloc.lower() in BOTWALL


def looks_like_captcha(text):
    t = (text or "").lower()
    return "captcha" in t and ("enter the characters" in t or "sorry, we just need" in t)


def verdict(chk, body_sniff=None):
    """Return a finding string, or None for healthy/inconclusive.
    Rule: bot-blocked, timeout, or connection-failed is NEVER a finding; a
    finding is only reported when a plain re-fetch confirms the destination is
    actually dead (404/410/5xx or soft-404)."""
    if chk["error"]:
        if botwalled(chk["url"]):
            return None  # inconclusive: host blocks automated checks
        return None  # transient network issue: do not report as finding
    fs = chk["final_status"]
    hops = len(chk["chain"])
    orig = urlparse(chk["url"])
    final = urlparse(chk["final_url"] or "")
    if fs in (404, 410):
        return f"{fs} at destination"
    if fs and fs >= 500:
        if fs == 503 and body_sniff and looks_like_captcha(body_sniff):
            return None
        return f"destination server error ({fs})"
    if fs == 403:
        return None  # likely bot-wall, inconclusive
    # soft 404: deep product URL -> bare homepage
    if final.path in ("", "/") and len(orig.path) > 1:
        if PRODUCT_HINT.search(orig.path):
            return "product page gone - redirects to homepage (soft 404)"
        return "redirects to homepage (page gone - soft 404)"
    # product URL -> category/search page
    if PRODUCT_HINT.search(orig.path) and CATEGORY_HINT.search(final.path or ""):
        return "product page appears gone - redirects to a category page"
    if hops >= 4:
        return f"long redirect chain ({hops} hops)"
    if is_proxy(chk["url"]):
        return None  # proxy attaches tag server-side; attribution unverifiable
    if AMAZON_RE.search(chk["url"]):
        q = parse_qs(orig.query)
        if "tag" not in q and "amzn.to" not in chk["url"]:
            return "missing affiliate tracking parameter (no tag= - earns nothing)"
    return None


RANK_KEYS = ["404", "410", "server error", "soft 404", "appears gone",
             "homepage", "redirect chain", "tracking"]


def rank(f):
    for i, k in enumerate(RANK_KEYS):
        if k in f["finding"]:
            return i
    return 99


def analyze(site_name, base, pages, max_links_per_page=14, progress=None):
    host = urlparse(base).netloc
    results = {"site": site_name, "base": base, "pages": [], "link_checks": []}
    checked = set()
    for page in pages:
        links, err = extract_links(page, host)
        pg = {"page": page, "error": err, "outbound_count": len(links)}
        results["pages"].append(pg)
        if err:
            continue
        aff = [l for l in links if is_affiliate(l)]
        other = [l for l in links if not is_affiliate(l)]
        cands = aff + other[: max(0, max_links_per_page - len(aff))]
        for u in cands[:max_links_per_page]:
            if u in checked:
                continue
            checked.add(u)
            chk = check_link(u)
            chk["page"] = page
            chk["is_affiliate"] = is_affiliate(u)
            chk["is_proxy"] = is_proxy(u)
            results["link_checks"].append(chk)
            if progress:
                progress(chk)
            time.sleep(0.3 + random.random() * 0.4)
        time.sleep(0.5)
    return results


def findings_for(results):
    findings = []
    for chk in results["link_checks"]:
        v = verdict(chk)
        if v:
            findings.append({"page": chk["page"], "url": chk["url"],
                             "finding": v, "hops": len(chk["chain"]),
                             "final_status": chk["final_status"],
                             "final_url": chk["final_url"],
                             "is_affiliate": chk["is_affiliate"]})
    findings.sort(key=rank)
    return findings


def run_audit(site_name, base, n_pages=8, work_dir=None):
    """Full pipeline: page discovery -> link extraction -> checks -> verdicts.
    Writes the JSON report into the project work/ dir and returns (report, path)."""
    wd = Path(work_dir) if work_dir else WORK_DIR
    wd.mkdir(parents=True, exist_ok=True)
    pages = pick_pages(base, n_pages)
    if not pages:
        pages = [base]
    results = analyze(site_name, base, pages)
    results["findings"] = findings_for(results)
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^a-z0-9]+", "-", site_name.lower()).strip("-") or "audit"
    out_path = wd / f"{safe}-{ts}.json"
    out_path.write_text(json.dumps(results, indent=1))
    return results, str(out_path)


def main():
    site_name, base = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    out_dir = sys.argv[4] if len(sys.argv) > 4 else str(WORK_DIR)
    pages = pick_pages(base, n)
    if not pages:
        pages = [base]
    print(f"{site_name}: scanning {len(pages)} pages", flush=True)
    results = analyze(site_name, base, pages)
    results["findings"] = findings_for(results)
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^a-z0-9]+", "-", site_name.lower()).strip("-") or "audit"
    out_path = Path(out_dir) / f"{safe}-{ts}.json"
    out_path.write_text(json.dumps(results, indent=1))
    print(f"{site_name}: {len(pages)} pages, {len(results['link_checks'])} links "
          f"checked, {len(results['findings'])} findings -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
