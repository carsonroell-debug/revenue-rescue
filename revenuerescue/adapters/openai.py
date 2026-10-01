"""OpenAI (ChatGPT) app-extension adapter.

Same engine, different platform shape: function-style tool definitions with
strict JSON schema, as used by ChatGPT app extensions / custom GPT actions.
Demonstrates the abstraction: only this file changes when targeting a new
agent platform. Not wired to any live OpenAI surface yet; kept for when the
connector is ported beyond Muse.
"""
from . import AgentAdapter
from ..audit import run_audit


class OpenAIAdapter(AgentAdapter):
    platform = "openai-apps"

    FUNCTIONS = [
        {
            "name": "audit_site",
            "description": (
                "Audit a publisher website for revenue leaks: dead affiliate "
                "links, missing tracking parameters, and soft-404 product "
                "redirects. Only confirmed findings are reported."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "site_name": {"type": "string"},
                    "base_url": {"type": "string"},
                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 12, "default": 8},
                },
                "required": ["site_name", "base_url"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]

    def describe(self):
        return {"platform": self.platform, "functions": self.FUNCTIONS}

    def invoke(self, tool, args):
        if tool != "audit_site":
            return {"ok": False, "error": f"unknown tool: {tool}"}
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
            "report_path": path,
        }
