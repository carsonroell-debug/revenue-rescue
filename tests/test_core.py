import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["REVENUE_RESCUE_SCRAPLING"] = "0"

from revenuerescue import audit
from revenuerescue.adapters.muse import MuseAdapter
from revenuerescue.adapters.openai import OpenAIAdapter
from revenuerescue.contracts import TOOLS
from revenuerescue.commerce import extract_commerce_context
from revenuerescue.crawler import crawl_pages
from revenuerescue.evidence import build_finding, tracking_evidence
from revenuerescue.intelligence import discontinued_offer, page_priority
from revenuerescue.security import UnsafeTarget, validate_public_http_url
from revenuerescue.jobs import get_finding, get_findings as get_job_findings
from revenuerescue.monitoring import diff_snapshots, due_monitors, snapshot_from_report
from revenuerescue.server import _valid_report_name, openapi_spec
from revenuerescue import storage
from revenuerescue.validation import ValidationError, validate_tool_args


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
        with patch.object(audit, "sitemap_urls", return_value=sitemap):
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

    def test_report_filename_validation_blocks_traversal(self):
        self.assertTrue(_valid_report_name("major-hifi-20261001.json"))
        self.assertFalse(_valid_report_name("../secret.json"))
        self.assertFalse(_valid_report_name("report.txt"))


class PipelineTests(unittest.TestCase):
    def test_run_audit_persists_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_results = {
                "site": "Example",
                "base": "https://example.com",
                "pages": [{"page": "https://example.com/review", "error": None, "outbound_count": 0}],
                "link_checks": [],
            }
            with patch.object(audit, "pick_pages", return_value=["https://example.com/review"]),                  patch.object(audit, "analyze", return_value=fake_results):
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
