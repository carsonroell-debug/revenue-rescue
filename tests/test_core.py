import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["REVENUE_RESCUE_SCRAPLING"] = "0"

from revenuerescue import audit
from revenuerescue.adapters.muse import MuseAdapter
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
