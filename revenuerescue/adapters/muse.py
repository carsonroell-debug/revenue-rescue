"""Muse connector adapter.

Maps Muse's tool invocations onto the audit engine. Per the platform research,
Muse connectors are submitted as either a hosted MCP endpoint ("Existing MCP")
or a raw API + OpenAPI spec ("Raw API"). This adapter defines the canonical
tool contract used by BOTH ingestion paths:

  tool name : audit_site
  args      : { site_name: str, base_url: str, max_pages?: int (1-12, default 8) }

The MCP server (revenuerescue/mcp_server.py) and the REST API
(revenuerescue/server.py) both delegate to this adapter, so the tool contract
stays identical regardless of which submission path Meta reviews.

Muse-specific notes (from platform research, Sept 2026):
- No auth is required for a first self-test; production directory listing
  should gate abuse with a per-user API key (Secure Credentials Store flow).
- Idempotent, narrow tools with typed fields and human-readable errors,
  per community best practice.
"""
from . import AgentAdapter
from ..audit import run_audit


class MuseAdapter(AgentAdapter):
    platform = "muse"

    TOOLS = [
        {
            "name": "audit_site",
            "description": (
                "Audit a publisher website for revenue leaks: dead affiliate "
                "links, missing tracking parameters, and soft-404 product "
                "redirects. Returns confirmed findings only; bot-blocked or "
                "timeout results are reported as inconclusive, never as leaks."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "site_name": {
                        "type": "string",
                        "description": "Human-readable site name, e.g. 'The Gadgeteer'",
                    },
                    "base_url": {
                        "type": "string",
                        "description": "Site root URL, e.g. 'https://the-gadgeteer.com'",
                    },
                    "max_pages": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 12,
                        "default": 8,
                        "description": "How many review pages to scan",
                    },
                },
                "required": ["site_name", "base_url"],
            },
        },
        {
            "name": "list_audits",
            "description": "List recent Revenue Rescue audit reports on this server.",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]

    def describe(self):
        return {
            "platform": self.platform,
            "connector_name": "Revenue Rescue",
            "tools": self.TOOLS,
            "auth": "none required for local self-test; API key in production",
            "example_prompts": [
                "Check my site for places where I am losing revenue",
                "Audit the-gadgeteer.com for dead affiliate links",
                "Are any of my Amazon links missing their tracking tag?",
            ],
        }

    def invoke(self, tool, args):
        if tool == "audit_site":
            site_name = args.get("site_name")
            base_url = args.get("base_url")
            if not site_name or not base_url:
                return {"ok": False, "error": "site_name and base_url are required"}
            max_pages = max(1, min(12, int(args.get("max_pages", 8))))
            report, path = run_audit(site_name, base_url, n_pages=max_pages)
            return {
                "ok": True,
                "summary": self.summarize(report),
                "findings": report["findings"],
                "stats": {
                    "pages": len(report["pages"]),
                    "links_checked": len(report["link_checks"]),
                    "findings": len(report["findings"]),
                },
                "report_path": path,
            }
        if tool == "list_audits":
            from pathlib import Path
            from ..audit import WORK_DIR
            files = sorted(Path(WORK_DIR).glob("*.json"), reverse=True)[:20]
            return {"ok": True, "audits": [f.name for f in files]}
        return {"ok": False, "error": f"unknown tool: {tool}"}
