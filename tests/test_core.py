import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["REVENUE_RESCUE_SCRAPLING"] = "0"

from revenuerescue import audit
from revenuerescue.adapters.muse import MuseAdapter
from revenuerescue.commerce import extract_commerce_context
from revenuerescue.crawler import crawl_pages
from revenuerescue.evidence import build_finding, tracking_evidence
from revenuerescue.security import UnsafeTarget, validate_public_http_url
from revenuerescue.jobs import get_findings as get_job_findings
from revenuerescue.monitoring import diff_snapshots, snapshot_from_report
from revenuerescue.server import _valid_report_name, openapi_spec


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


class JobContractTests(unittest.TestCase):
    def test_nonexistent_job_returns_clean_error(self):
        result = get_job_findings("00000000-0000-0000-0000-000000000000")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "audit not found")


class ContractTests(unittest.TestCase):
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
