"""LinkRescue: link-health + revenue-leak audit engine with agent adapters."""
from .audit import run_audit, pick_pages, extract_links, check_link, verdict, findings_for

# NOTE: package version lives in revenuerescue/version.py (single source of truth).
__all__ = ["run_audit", "pick_pages", "extract_links", "check_link",
           "verdict", "findings_for"]
