import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["REVENUE_RESCUE_SCRAPLING"] = "0"

from revenuerescue import audit
from revenuerescue import robots
from revenuerescue.adapters.muse import MuseAdapter
from revenuerescue.adapters.openai import OpenAIAdapter
from revenuerescue.contracts import TOOLS
from revenuerescue.commerce import extract_commerce_context
from revenuerescue.crawler import crawl_pages
from revenuerescue.evidence import build_finding, tracking_evidence
from revenuerescue.intelligence import discontinued_offer, page_priority
from revenuerescue.security import UnsafeTarget, validate_public_http_url
from revenuerescue.jobs import get_finding, get_findings as get_job_findings
from revenuerescue.jobs import reap_orphaned_jobs
from revenuerescue.monitoring import diff_snapshots, due_monitors, snapshot_from_report
from revenuerescue.server import openapi_spec
from revenuerescue.config import RuntimeConfig
from revenuerescue import storage
from revenuerescue.validation import ValidationError, validate_tool_args
from revenuerescue.errors import invalid_input, not_found, rate_limited
from revenuerescue.version import __version__


class VerdictTests(unittest.TestCase):
    def test_404_is_confirmed_finding(self):
        chk = {
            "url": "https://merchant.test/product/123",
            "chain": [],
            "final_status": 404,
            "final_url": "https://merchant.test/product/123",
            "error": None,
        }
        self.assertIn("404", audit.verdict(chk))

    def test_timeout_is_never_a_finding(self):
        chk = {
            "url": "https://merchant.test/product/123",
            "chain": [],
            "final_status": None,
            "final_url": None,
            "error": "connection failed x3 (Timeout)",
        }
        self.assertIsNone(audit.verdict(chk))

    def test_affiliate_proxy_never_gets_missing_tag_finding(self):
        chk = {
            "url": "https://geni.us/example",
            "chain": [],
            "final_status": 200,
            "final_url": "https://www.amazon.com/dp/B000000000",
            "error": None,
        }
        self.assertIsNone(audit.verdict(chk))

    def test_amazon_without_tag_is_flagged(self):
        chk = {
            "url": "https://www.amazon.com/dp/B000000000",
            "chain": [],
            "final_status": 200,
            "final_url": "https://www.amazon.com/dp/B000000000",
            "error": None,
        }
        self.assertIn("tracking", audit.verdict(chk))

    def test_product_redirect_to_homepage_is_soft_404(self):
        chk = {
            "url": "https://merchant.test/products/widget",
            "chain": [{"status": 301, "url": "https://merchant.test/products/widget"}],
            "final_status": 200,
            "final_url": "https://merchant.test/",
            "error": None,
        }
        self.assertIn("soft 404", audit.verdict(chk))


    def test_direct_affiliate_tracking_drop_is_flagged(self):
        chk = {
            "url": "https://amazon.com/dp/ABC?tag=cars-20",
            "chain": [{"status": 301, "url": "https://amazon.com/dp/ABC?tag=cars-20"}],
            "final_status": 200,
            "final_url": "https://amazon.com/dp/ABC",
            "error": None,
        }
        result = audit.verdict(chk)
        self.assertIn("tracking parameter dropped", result)

    def test_proxy_tracking_drop_remains_inconclusive(self):
        chk = {
            "url": "https://geni.us/widget?tag=cars-20",
            "chain": [{"status": 302, "url": "https://geni.us/widget?tag=cars-20"}],
            "final_status": 200,
            "final_url": "https://amazon.com/dp/ABC",
            "error": None,
        }
        self.assertIsNone(audit.verdict(chk))

    def test_503_from_botwall_host_is_inconclusive(self):
        chk = {
            "url": "https://www.rei.com/product/123",
            "chain": [],
            "final_status": 503,
            "final_url": "https://www.rei.com/product/123",
            "error": None,
        }
        # Bot-wall hosts serve 503 challenges; never a finding.
        self.assertIsNone(audit.verdict(chk))

    def test_503_from_ordinary_host_is_a_finding(self):
        chk = {
            "url": "https://merchant.test/product/123",
            "chain": [],
            "final_status": 503,
            "final_url": "https://merchant.test/product/123",
            "error": None,
        }
        self.assertEqual(audit.verdict(chk), "destination server error (503)")


class FetchUpgradeTests(unittest.TestCase):
    def test_captcha_upgraded_content_keeps_original(self):
        class FakeOriginal:
            status_code = 403
            text = "forbidden"
            url = "https://example.test/page"

        class FakeUpgraded:
            status_code = 200
            text = "please prove you are human: enter the characters captcha"
            url = "https://example.test/page"
            fetch_tier = "scrapling-dynamic"

        original = FakeOriginal()
        with patch.object(audit, "_scrapling_enabled", return_value=True), \
             patch.object(audit, "_scrapling_fetch", return_value=FakeUpgraded()):
            out = audit._maybe_upgrade_fetch("https://example.test/page", original, timeout=5)
        # A rendered bot-wall must not masquerade as a clean 200.
        self.assertIs(out, original)

    def test_clean_upgraded_content_is_adopted(self):
        class FakeOriginal:
            status_code = 403
            text = "forbidden"
            url = "https://example.test/page"

        class FakeUpgraded:
            status_code = 200
            text = "<html><body>" + "real content " * 100 + "</body></html>"
            url = ""
            fetch_tier = "scrapling-dynamic"

        with patch.object(audit, "_scrapling_enabled", return_value=True), \
             patch.object(audit, "_scrapling_fetch", return_value=FakeUpgraded()):
            out = audit._maybe_upgrade_fetch("https://example.test/page", FakeOriginal(), timeout=5)
        self.assertEqual(out.status_code, 200)
        self.assertEqual(out.url, "https://example.test/page")


class FakeLinkResponse:
    """Minimal requests.Response stand-in for check_link tests."""

    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url
        self.history = []
        self.headers = {}

    def close(self):
        pass


class RobotsTxtTests(unittest.TestCase):
    def setUp(self):
        robots.clear_cache()

    def tearDown(self):
        robots.clear_cache()

    def _fetcher(self, mapping):
        calls = []

        def fetch(host):
            calls.append(host)
            return mapping.get(host)

        fetch.calls = calls
        return fetch

    def test_disallowed_path_is_not_allowed(self):
        f = self._fetcher({"example.com": "User-agent: *\nDisallow: /private/\n"})
        self.assertFalse(robots.is_allowed("https://example.com/private/page", fetcher=f))
        self.assertTrue(robots.is_allowed("https://example.com/public", fetcher=f))

    def test_specific_ua_group_beats_wildcard(self):
        # Our fetcher UA starts with "Mozilla/5.0", so the mozilla group is
        # the most specific match and wins over "*".
        txt = "User-agent: mozilla\nDisallow: /x\n\nUser-agent: *\nDisallow: /y\n"
        f = self._fetcher({"example.com": txt})
        self.assertFalse(robots.is_allowed("https://example.com/x", fetcher=f))
        self.assertTrue(robots.is_allowed("https://example.com/y", fetcher=f))

    def test_wildcard_group_applies_when_nothing_specific_matches(self):
        txt = "User-agent: googlebot\nDisallow: /secret\n\nUser-agent: *\nDisallow: /tmp\n"
        f = self._fetcher({"example.com": txt})
        self.assertFalse(robots.is_allowed("https://example.com/tmp/f", fetcher=f))
        self.assertTrue(robots.is_allowed("https://example.com/secret", fetcher=f))

    def test_allow_beats_disallow_on_longest_match(self):
        txt = "User-agent: *\nDisallow: /private/\nAllow: /private/public/\n"
        f = self._fetcher({"example.com": txt})
        self.assertTrue(robots.is_allowed("https://example.com/private/public/p", fetcher=f))
        self.assertFalse(robots.is_allowed("https://example.com/private/other", fetcher=f))

    def test_star_and_dollar_patterns(self):
        txt = "User-agent: *\nDisallow: /*?\nDisallow: /tmp$\n"
        f = self._fetcher({"example.com": txt})
        self.assertFalse(robots.is_allowed("https://example.com/page?x=1", fetcher=f))
        self.assertTrue(robots.is_allowed("https://example.com/page", fetcher=f))
        self.assertFalse(robots.is_allowed("https://example.com/tmp", fetcher=f))
        self.assertTrue(robots.is_allowed("https://example.com/tmp/", fetcher=f))

    def test_empty_disallow_allows_all(self):
        f = self._fetcher({"example.com": "User-agent: *\nDisallow:\n"})
        self.assertTrue(robots.is_allowed("https://example.com/anything", fetcher=f))

    def test_fetch_failure_allows(self):
        f = self._fetcher({})  # no entry -> robots.txt unreachable
        self.assertTrue(robots.is_allowed("https://example.com/anything", fetcher=f))

    def test_fetcher_exception_allows(self):
        def boom(host):
            raise RuntimeError("dns blew up")

        self.assertTrue(robots.is_allowed("https://example.com/anything", fetcher=boom))

    def test_caching_avoids_refetch(self):
        f = self._fetcher({"example.com": "User-agent: *\nDisallow: /x\n"})
        robots.is_allowed("https://example.com/a", fetcher=f)
        robots.is_allowed("https://example.com/b", fetcher=f)
        self.assertEqual(f.calls, ["example.com"])

    def test_check_link_skips_disallowed_without_finding(self):
        with patch.object(audit, "robots_allowed", return_value=False), \
             patch.object(audit, "validate_public_http_url", side_effect=lambda u: u):
            chk = audit.check_link("https://example.com/product/1")
        self.assertIn("robots.txt", chk["error"])
        self.assertIsNone(chk["final_status"])
        # Honest-verdict invariant: exclusion is never a finding.
        self.assertIsNone(audit.verdict(chk))

    def test_check_link_allowed_proceeds(self):
        resp = FakeLinkResponse(200, "https://example.com/product/1")
        with patch.object(audit, "robots_allowed", return_value=True), \
             patch.object(audit, "validate_public_http_url", side_effect=lambda u: u), \
             patch.object(audit, "safe_get", return_value=resp):
            chk = audit.check_link("https://example.com/product/1")
        self.assertEqual(chk["final_status"], 200)
        self.assertIsNone(chk["error"])

    def test_pick_pages_filters_disallowed(self):
        sitemap = [
            ("https://example.com/best-widgets", "2026-10-01"),
            ("https://example.com/blocked-page", "2026-10-01"),
        ]
        with patch.object(audit, "sitemap_urls", return_value=sitemap), \
             patch.object(audit, "robots_allowed",
                          side_effect=lambda u: "blocked" not in u):
            pages = audit.pick_pages("https://example.com", 8)
        self.assertEqual(pages, ["https://example.com/best-widgets"])


class SecurityTests(unittest.TestCase):
    def test_blocks_loopback(self):
        with self.assertRaises(UnsafeTarget):
            validate_public_http_url("http://127.0.0.1/admin")

    def test_blocks_private_ip(self):
        with self.assertRaises(UnsafeTarget):
            validate_public_http_url("http://10.0.0.8/internal")

    def test_blocks_non_http_scheme(self):
        with self.assertRaises(UnsafeTarget):
            validate_public_http_url("file:///etc/passwd")


class EvidenceTests(unittest.TestCase):
    def test_tracking_diff_reports_dropped_params(self):
        evidence = tracking_evidence(
            "https://merchant.test/product?tag=cars-20&x=1",
            "https://merchant.test/product?x=1",
        )
        self.assertEqual(evidence["dropped_tracking_params"], ["tag"])

    def test_affiliate_cta_increases_risk(self):
        chk = {
            "page": "https://publisher.test/best-widget",
            "url": "https://amazon.com/dp/ABC",
            "final_url": "https://amazon.com/dp/ABC",
            "final_status": 200,
            "chain": [],
            "is_affiliate": True,
            "is_cta": True,
            "anchor_text": "Buy now",
            "heading": "Our top pick",
            "context": "Our top pick Buy now",
        }
        finding = build_finding(
            chk,
            "missing affiliate tracking parameter (no tag= - earns nothing)",
        )
        self.assertEqual(finding["issue_type"], "AFFILIATE_TRACKING_MISSING")
        self.assertEqual(finding["severity"], "critical")
        self.assertGreaterEqual(finding["revenue_risk_score"], 92)


    def test_finding_id_is_stable(self):
        chk = {
            "page": "https://publisher.test/post",
            "url": "https://merchant.test/item",
            "final_url": "https://merchant.test/item",
            "final_status": 404,
            "chain": [],
            "is_affiliate": False,
            "is_cta": True,
        }
        first = build_finding(chk, "404 at destination")
        second = build_finding(chk, "404 at destination")
        self.assertEqual(first["finding_id"], second["finding_id"])
        self.assertTrue(first["finding_id"].startswith("rr_"))


class IntelligenceTests(unittest.TestCase):
    def test_commercial_pages_rank_above_low_value_pages(self):
        best = page_priority("https://example.com/best-running-shoes")
        privacy = page_priority("https://example.com/privacy-policy")
        self.assertGreater(best, privacy)

    def test_pick_pages_prioritizes_commercial_urls(self):
        sitemap = [
            ("https://example.com/privacy-policy", "2026-10-01"),
            ("https://example.com/best-running-shoes", "2025-01-01"),
            ("https://example.com/about", "2026-10-01"),
        ]
        # robots check is stubbed: no live robots.txt fetch in tests.
        with patch.object(audit, "sitemap_urls", return_value=sitemap), \
             patch.object(audit, "robots_allowed", return_value=True):
            pages = audit.pick_pages("https://example.com", 1)
        self.assertEqual(pages, ["https://example.com/best-running-shoes"])

    def test_discontinued_is_actionable_but_out_of_stock_is_not(self):
        discontinued = {
            "offers": [{"availability": "https://schema.org/Discontinued", "price": "99"}]
        }
        temporary = {
            "offers": [{"availability": "https://schema.org/OutOfStock", "price": "99"}]
        }
        self.assertIsNotNone(discontinued_offer(discontinued))
        self.assertIsNone(discontinued_offer(temporary))


class CommerceTests(unittest.TestCase):
    def test_extracts_product_offer_jsonld(self):
        from bs4 import BeautifulSoup

        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context":"https://schema.org",
            "@type":"Product",
            "name":"Widget Pro",
            "sku":"WP-1",
            "offers":{
              "@type":"Offer",
              "price":"499.00",
              "priceCurrency":"CAD",
              "availability":"https://schema.org/InStock"
            }
          }
          </script>
        </head><body></body></html>
        """
        ctx = extract_commerce_context(BeautifulSoup(html, "html.parser"))
        self.assertTrue(ctx["has_product_schema"])
        self.assertTrue(ctx["has_offer_schema"])
        self.assertEqual(ctx["products"][0]["name"], "Widget Pro")
        self.assertEqual(ctx["offers"][0]["price"], "499.00")


    def test_findings_for_adds_discontinued_offer(self):
        results = {
            "link_checks": [],
            "pages": [{
                "page": "https://shop.test/widget",
                "status": 200,
                "commerce": {
                    "has_product_schema": True,
                    "has_offer_schema": True,
                    "products": [{"name": "Widget"}],
                    "offers": [{
                        "availability": "https://schema.org/Discontinued",
                        "price": "99",
                        "currency": "CAD",
                        "url": "https://shop.test/widget",
                    }],
                },
            }],
        }
        findings = audit.findings_for(results)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["issue_type"], "OFFER_DISCONTINUED")


class RuntimeTests(unittest.TestCase):
    def test_chrome_discovery_uses_shared_playwright_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "chromium-123" / "chrome-linux64" / "chrome"
            binary.parent.mkdir(parents=True)
            binary.write_text("")
            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": tmp}, clear=False):
                self.assertEqual(audit._chrome_executable(), str(binary))


class CrawleeTests(unittest.IsolatedAsyncioTestCase):
    async def test_crawlee_orchestrates_injected_fetcher_without_network_fetch(self):
        class FakeResponse:
            status_code = 200
            url = "https://example.com/a"
            text = "<html><body><a href='https://merchant.test/x'>Buy</a></body></html>"

        def fake_fetch(url):
            response = FakeResponse()
            response.url = url
            return response

        with patch("revenuerescue.crawler.validate_public_http_url", return_value="ok"):
            rows = await crawl_pages(
                ["https://example.com/a", "https://example.com/b"],
                fake_fetch,
                max_concurrency=2,
                max_tasks_per_minute=1000,
            )

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == 200 for row in rows))
        self.assertTrue(all(row["error"] is None for row in rows))


class MonitoringTests(unittest.TestCase):
    def test_detects_tracking_drop_and_destination_change(self):
        previous = {
            "links": {
                "page|url": {
                    "page": "https://publisher.test/post",
                    "url": "https://merchant.test/item?tag=cars-20",
                    "final_url": "https://merchant.test/item?tag=cars-20",
                    "final_status": 200,
                    "is_affiliate": True,
                    "is_cta": True,
                    "tracking_final": {"tag": ["cars-20"]},
                }
            },
            "findings": {},
            "pages": {},
        }
        current = {
            "links": {
                "page|url": {
                    "page": "https://publisher.test/post",
                    "url": "https://merchant.test/item?tag=cars-20",
                    "final_url": "https://merchant.test/new-item",
                    "final_status": 200,
                    "is_affiliate": True,
                    "is_cta": True,
                    "tracking_final": {},
                }
            },
            "findings": {},
            "pages": {},
        }
        events = diff_snapshots(previous, current)
        event_types = {event["event_type"] for event in events}
        self.assertIn("DESTINATION_CHANGED", event_types)
        self.assertIn("TRACKING_DROPPED", event_types)
        tracking = next(e for e in events if e["event_type"] == "TRACKING_DROPPED")
        self.assertEqual(tracking["severity"], "critical")

    def test_detects_new_and_resolved_findings(self):
        old_finding = {
            "issue_type": "BROKEN_DESTINATION",
            "severity": "high",
            "page": "p",
            "url": "u",
            "finding": "404",
        }
        new_finding = {
            "issue_type": "AFFILIATE_TRACKING_MISSING",
            "severity": "critical",
            "page": "p2",
            "url": "u2",
            "finding": "tracking",
        }
        previous = {"links": {}, "pages": {}, "findings": {"old": old_finding}}
        current = {"links": {}, "pages": {}, "findings": {"new": new_finding}}
        events = diff_snapshots(previous, current)
        types = {e["event_type"] for e in events}
        self.assertEqual(types, {"NEW_REVENUE_RISK", "REVENUE_RISK_RESOLVED"})

    def test_detects_structured_offer_change(self):
        previous = {
            "links": {},
            "findings": {},
            "pages": {
                "https://publisher.test/deal": {
                    "commerce_offers": [{"price": "499", "currency": "CAD", "availability": "InStock"}]
                }
            },
        }
        current = {
            "links": {},
            "findings": {},
            "pages": {
                "https://publisher.test/deal": {
                    "commerce_offers": [{"price": "549", "currency": "CAD", "availability": "InStock"}]
                }
            },
        }
        events = diff_snapshots(previous, current)
        self.assertEqual(events[0]["event_type"], "OFFER_DATA_CHANGED")


class StorageTests(unittest.TestCase):
    def test_local_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(storage, "DATABASE_URL", ""), patch.object(storage, "STATE_DIR", Path(tmp)):
                storage.put_state("audit_jobs", "00000000-0000-0000-0000-000000000001", {"ok": True, "x": 1})
                loaded = storage.get_state("audit_jobs", "00000000-0000-0000-0000-000000000001")
                self.assertEqual(loaded["x"], 1)
                self.assertTrue(storage.delete_state("audit_jobs", "00000000-0000-0000-0000-000000000001"))
                self.assertIsNone(storage.get_state("audit_jobs", "00000000-0000-0000-0000-000000000001"))

    def test_unsupported_state_kind_is_rejected_for_postgres(self):
        with patch.object(storage, "DATABASE_URL", "postgresql://configured"):
            with self.assertRaises(ValueError):
                storage._table("unknown")

    def test_prune_deletes_only_old_audit_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(storage, "DATABASE_URL", ""), patch.object(storage, "STATE_DIR", Path(tmp)):
                old_id = "00000000-0000-0000-0000-000000000001"
                new_id = "00000000-0000-0000-0000-000000000002"
                storage.put_state("audit_jobs", old_id, {"ok": True})
                storage.put_state("audit_jobs", new_id, {"ok": True})
                old_path = Path(tmp) / "audit_jobs" / f"{old_id}.json"
                ancient = time.time() - 100 * 86400
                os.utime(old_path, (ancient, ancient))
                deleted = storage.prune_states_older_than("audit_jobs", max_age_days=90)
                self.assertEqual(deleted, 1)
                self.assertIsNone(storage.get_state("audit_jobs", old_id))
                self.assertIsNotNone(storage.get_state("audit_jobs", new_id))

    def test_prune_refuses_non_audit_kinds(self):
        with self.assertRaises(ValueError):
            storage.prune_states_older_than("monitors")


    def test_due_monitor_selection_respects_cadence(self):
        now = 10_000.0
        monitors = [
            {
                "ok": True,
                "monitor_id": "00000000-0000-0000-0000-000000000001",
                "cadence_hours": 1,
                "last_run_at": now - 7200,
            },
            {
                "ok": True,
                "monitor_id": "00000000-0000-0000-0000-000000000002",
                "cadence_hours": 24,
                "last_run_at": now - 60,
            },
        ]
        with patch("revenuerescue.monitoring.list_state", return_value=monitors):
            due = due_monitors(now=now)
        self.assertEqual(len(due), 1)
        self.assertEqual(
            due[0]["monitor_id"],
            "00000000-0000-0000-0000-000000000001",
        )


class JobContractTests(unittest.TestCase):
    def test_nonexistent_job_returns_clean_error(self):
        result = get_job_findings("00000000-0000-0000-0000-000000000000")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "audit not found")


class ReaperTests(unittest.TestCase):
    """Crash recovery: jobs stuck in queued/running get released as failed.

    All hermetic: temp STATE_DIR, injected ``now`` and thresholds — no
    sleeping, no live network, no real executor involvement.
    """

    def _seed(self, tmp, jobs):
        from revenuerescue import storage as _storage

        with patch.object(_storage, "DATABASE_URL", ""), patch.object(
            _storage, "STATE_DIR", Path(tmp)
        ):
            for job in jobs:
                _storage.put_state("audit_jobs", job["audit_id"], job)

    def _reap(self, tmp, **kwargs):
        from revenuerescue import storage as _storage

        with patch.object(_storage, "DATABASE_URL", ""), patch.object(
            _storage, "STATE_DIR", Path(tmp)
        ):
            return reap_orphaned_jobs(**kwargs)

    def _load(self, tmp, audit_id):
        from revenuerescue import storage as _storage

        with patch.object(_storage, "DATABASE_URL", ""), patch.object(
            _storage, "STATE_DIR", Path(tmp)
        ):
            return _storage.get_state("audit_jobs", audit_id)

    def _job(self, audit_id, status, **fields):
        job = {
            "ok": True,
            "audit_id": audit_id,
            "status": status,
            "site_name": "example",
            "base_url": "https://example.com",
            "max_pages": 8,
        }
        job.update(fields)
        return job

    def test_old_running_job_is_reaped_as_failed(self):
        now = 100_000.0
        rid = "00000000-0000-0000-0000-0000000000a1"
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, [
                self._job(rid, "running", created_at=now - 7200,
                          started_at=now - 3600),
            ])
            out = self._reap(tmp, now=now, threshold_seconds=1800)
            self.assertTrue(out["ok"])
            self.assertEqual(out["reaped"], 1)
            self.assertEqual(out["audit_ids"], [rid])
            job = self._load(tmp, rid)
            self.assertEqual(job["status"], "failed")
            self.assertFalse(job["ok"])
            self.assertIn("orphaned", job["error"])
            self.assertIn("running", job["error"])
            self.assertEqual(job["completed_at"], now)

    def test_old_queued_job_is_reaped(self):
        now = 100_000.0
        rid = "00000000-0000-0000-0000-0000000000a2"
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, [
                self._job(rid, "queued", created_at=now - 7200),
            ])
            out = self._reap(tmp, now=now, threshold_seconds=1800)
            self.assertEqual(out["reaped"], 1)
            job = self._load(tmp, rid)
            self.assertEqual(job["status"], "failed")
            self.assertIn("queued", job["error"])

    def test_fresh_jobs_are_untouched(self):
        now = 100_000.0
        running_id = "00000000-0000-0000-0000-0000000000b1"
        queued_id = "00000000-0000-0000-0000-0000000000b2"
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, [
                self._job(running_id, "running", created_at=now - 600,
                          started_at=now - 60),
                self._job(queued_id, "queued", created_at=now - 60),
            ])
            out = self._reap(tmp, now=now, threshold_seconds=1800)
            self.assertEqual(out["reaped"], 0)
            self.assertEqual(out["audit_ids"], [])
            self.assertEqual(self._load(tmp, running_id)["status"], "running")
            self.assertEqual(self._load(tmp, queued_id)["status"], "queued")

    def test_terminal_jobs_are_untouched(self):
        now = 100_000.0
        done_id = "00000000-0000-0000-0000-0000000000c1"
        failed_id = "00000000-0000-0000-0000-0000000000c2"
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, [
                self._job(done_id, "completed", created_at=now - 7200,
                          started_at=now - 7100, completed_at=now - 7000),
                self._job(failed_id, "failed", created_at=now - 7200,
                          completed_at=now - 7000, error="boom"),
            ])
            out = self._reap(tmp, now=now, threshold_seconds=1800)
            self.assertEqual(out["reaped"], 0)
            self.assertEqual(self._load(tmp, done_id)["status"], "completed")
            failed = self._load(tmp, failed_id)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"], "boom")

    def test_running_job_missing_started_at_is_reaped(self):
        # A partial/corrupt write can never make progress.
        now = 100_000.0
        rid = "00000000-0000-0000-0000-0000000000d1"
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, [self._job(rid, "running", created_at=now - 60)])
            out = self._reap(tmp, now=now, threshold_seconds=1800)
            self.assertEqual(out["reaped"], 1)
            job = self._load(tmp, rid)
            self.assertEqual(job["status"], "failed")
            self.assertIn("unknown duration", job["error"])

    def test_reaped_error_never_claims_a_finding(self):
        # Honest-verdict discipline: an orphaned job is a failure, not a result.
        now = 100_000.0
        rid = "00000000-0000-0000-0000-0000000000e1"
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, [
                self._job(rid, "running", created_at=now - 7200,
                          started_at=now - 3600),
            ])
            self._reap(tmp, now=now, threshold_seconds=1800)
            job = self._load(tmp, rid)
            self.assertNotIn("findings", job)
            self.assertFalse(job.get("ok"))


    def test_get_finding_explains_evidence(self):
        finding = {
            "finding_id": "rr_abc123",
            "issue_type": "BROKEN_DESTINATION",
            "finding": "404 at destination",
            "severity": "high",
            "confidence": 0.99,
            "revenue_risk_score": 95,
            "recommendation": "Replace the link.",
            "evidence": {"anchor_text": "Buy now"},
        }
        job = {
            "ok": True,
            "status": "completed",
            "findings": [finding],
        }
        with patch("revenuerescue.jobs.get_job", return_value=job):
            result = get_finding("00000000-0000-0000-0000-000000000001", "rr_abc123")
        self.assertTrue(result["ok"])
        self.assertIn("404 at destination", result["explanation"])
        self.assertEqual(result["recommended_action"], "Replace the link.")


class ValidationTests(unittest.TestCase):
    def test_defaults_and_normalizes_audit_args(self):
        args = validate_tool_args("start_audit", {
            "site_name": "Example",
            "base_url": "https://example.com",
        })
        self.assertEqual(args["max_pages"], 8)

    def test_rejects_non_http_url(self):
        with self.assertRaises(ValidationError):
            validate_tool_args("start_audit", {
                "site_name": "Example",
                "base_url": "file:///etc/passwd",
            })

    def test_rejects_out_of_range_page_count(self):
        with self.assertRaises(ValidationError):
            validate_tool_args("start_audit", {
                "site_name": "Example",
                "base_url": "https://example.com",
                "max_pages": 5000,
            })

    def test_rejects_unexpected_fields(self):
        with self.assertRaises(ValidationError):
            validate_tool_args("monitor_site", {
                "site_name": "Example",
                "base_url": "https://example.com",
                "admin_token": "secret",
            })


class ReleaseEngineeringTests(unittest.TestCase):
    def test_version_is_semver_like(self):
        parts = __version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(part.isdigit() for part in parts))

    def test_error_envelopes_are_machine_readable(self):
        bad = invalid_input("bad input", field="base_url")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "INVALID_INPUT")
        self.assertFalse(bad["error"]["retryable"])
        self.assertEqual(bad["error"]["details"]["field"], "base_url")

        missing = not_found("monitor", "abc")
        self.assertEqual(missing["error"]["code"], "NOT_FOUND")
        self.assertEqual(missing["error"]["details"]["id"], "abc")

        limited = rate_limited(30)
        self.assertTrue(limited["error"]["retryable"])
        self.assertEqual(limited["error"]["details"]["retry_after_seconds"], 30)

    def test_storage_health_local_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(storage, "DATABASE_URL", ""), patch.object(storage, "STATE_DIR", Path(tmp)):
                result = storage.storage_health()
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "local-json")


class ContractTests(unittest.TestCase):
    def test_platform_adapters_share_same_tool_names(self):
        canonical = [tool["name"] for tool in TOOLS]
        muse = [tool["name"] for tool in MuseAdapter().describe()["tools"]]
        openai = [fn["name"] for fn in OpenAIAdapter().describe()["functions"]]
        self.assertEqual(muse, canonical)
        self.assertEqual(openai, canonical)

    def test_openapi_exposes_modern_operations(self):
        spec = openapi_spec("https://revenue-rescue.example/")
        operation_ids = {
            operation["operationId"]
            for path in spec["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        }
        self.assertTrue({
            "startAudit",
            "getAuditStatus",
            "getFindings",
            "explainFinding",
            "createMonitor",
            "getMonitorStatus",
            "runMonitorNow",
            "getMonitorChanges",
        }.issubset(operation_ids))


    def test_muse_contract_has_required_fields(self):
        desc = MuseAdapter().describe()
        audit_tool = next(t for t in desc["tools"] if t["name"] == "audit_site")
        schema = audit_tool["input_schema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["required"]), {"site_name", "base_url"})

    def test_openapi_exposes_audit_operation(self):
        spec = openapi_spec("https://revenue-rescue.example/")
        self.assertEqual(spec["openapi"], "3.0.3")
        self.assertEqual(
            spec["paths"]["/api/v1/audits"]["post"]["operationId"],
            "auditSite",
        )

    def test_production_config_requires_auth_cron_and_database(self):
        cfg = RuntimeConfig(
            environment="production",
            api_token="",
            cron_secret="",
            database_url="",
            scrapling_enabled=True,
            port=8787,
        )
        problems = cfg.problems()
        self.assertEqual(len(problems), 3)

    def test_development_config_allows_local_fallbacks(self):
        cfg = RuntimeConfig(
            environment="development",
            api_token="",
            cron_secret="",
            database_url="",
            scrapling_enabled=False,
            port=8787,
        )
        self.assertEqual(cfg.problems(), [])


class PipelineTests(unittest.TestCase):
    def test_run_audit_persists_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_results = {
                "site": "Example",
                "base": "https://example.com",
                "pages": [{"page": "https://example.com/review", "error": None, "outbound_count": 0}],
                "link_checks": [],
            }
            # run_audit validates the base URL via live DNS; stub it so the
            # test is hermetic (sandbox/CI DNS may not resolve publicly).
            with patch.object(audit, "pick_pages", return_value=["https://example.com/review"]),                  patch.object(audit, "analyze", return_value=fake_results),                  patch.object(audit, "validate_public_http_url",
                               side_effect=lambda url: url):
                report, path = audit.run_audit(
                    "Example",
                    "https://example.com",
                    n_pages=1,
                    work_dir=tmp,
                )
            self.assertEqual(report["findings"], [])
            self.assertTrue(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
