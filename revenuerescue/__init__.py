"""Revenue Rescue: link-health + revenue-leak audit engine with agent adapters."""
from .audit import run_audit, pick_pages, extract_links, check_link, verdict, findings_for

__version__ = "0.1.0"
__all__ = ["run_audit", "pick_pages", "extract_links", "check_link",
           "verdict", "findings_for"]
