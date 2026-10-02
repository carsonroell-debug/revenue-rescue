"""Muse-shaped adapter over Revenue Rescue's canonical contracts.

This adapter intentionally contains no platform-specific product logic.
Contracts live in revenuerescue.contracts; execution delegates to the same
jobs/monitoring services used by MCP and REST.
"""
from . import AgentAdapter
from ..audit import run_audit
from ..contracts import TOOLS
from ..jobs import get_finding, get_findings, get_job, start_audit_job
from ..monitoring import create_monitor, get_changes, get_monitor, run_monitor
from ..validation import ValidationError, validate_tool_args


class MuseAdapter(AgentAdapter):
    platform = "muse"

    TOOLS = TOOLS

    def describe(self):
        return {
            "platform": self.platform,
            "connector_name": "Revenue Rescue",
            "tools": self.TOOLS,
            "auth": "bearer token supported in production",
            "example_prompts": [
                "Check my site for confirmed revenue risks",
                "Start an audit of my website and tell me when it finishes",
                "Explain the highest-risk finding",
                "Monitor this site daily and tell me what changes",
            ],
        }

    def invoke(self, tool, args):
        try:
            args = validate_tool_args(tool, args)
        except KeyError:
            return {"ok": False, "error": f"unknown tool: {tool}"}
        except ValidationError as exc:
            return {"ok": False, "error": str(exc)}

        if tool == "audit_site":
            site_name = args.get("site_name")
            base_url = args.get("base_url")
            if not site_name or not base_url:
                return {"ok": False, "error": "site_name and base_url are required"}
            max_pages = max(1, min(50, int(args.get("max_pages", 8))))
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

        if tool == "start_audit":
            return start_audit_job(
                args.get("site_name"),
                args.get("base_url"),
                max_pages=args.get("max_pages", 8),
            )

        if tool == "get_audit_status":
            return get_job(args.get("audit_id", ""))

        if tool == "get_findings":
            return get_findings(
                args.get("audit_id", ""),
                severity=args.get("severity"),
                issue_type=args.get("issue_type"),
            )

        if tool == "explain_finding":
            return get_finding(
                args.get("audit_id", ""),
                args.get("finding_id", ""),
            )

        if tool == "monitor_site":
            return create_monitor(
                args.get("site_name"),
                args.get("base_url"),
                max_pages=args.get("max_pages", 8),
                cadence_hours=args.get("cadence_hours", 24),
            )

        if tool == "run_monitor_now":
            return run_monitor(args.get("monitor_id", ""))

        if tool == "get_monitor_status":
            monitor = get_monitor(args.get("monitor_id", ""))
            if not monitor.get("ok"):
                return monitor
            return {
                "ok": True,
                "monitor_id": monitor.get("monitor_id"),
                "site_name": monitor.get("site_name"),
                "base_url": monitor.get("base_url"),
                "cadence_hours": monitor.get("cadence_hours"),
                "last_run_at": monitor.get("last_run_at"),
                "has_baseline": monitor.get("baseline") is not None,
                "last_change_count": len(monitor.get("last_changes", [])),
            }

        if tool == "get_monitor_changes":
            return get_changes(args.get("monitor_id", ""))

        return {"ok": False, "error": f"unknown tool: {tool}"}
