"""Persistent monitoring and change detection for Revenue Rescue.

The monitor engine turns one-off audits into recurring value. It stores a
baseline snapshot of deterministic evidence and emits machine-readable change
events on later runs.

This local JSON backend is intentionally replaceable. The MCP/API contracts are
designed so Postgres/Supabase + a real scheduler can take over without changing
agent-facing tool names.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .audit import WORK_DIR, run_audit
from .security import validate_public_http_url

MONITOR_DIR = WORK_DIR / "monitors"
MONITOR_DIR.mkdir(parents=True, exist_ok=True)


def _path(monitor_id: str) -> Path:
    if not monitor_id or any(ch not in "0123456789abcdef-" for ch in monitor_id.lower()):
        raise ValueError("invalid monitor id")
    return MONITOR_DIR / f"{monitor_id}.json"


def _tracking(url: str | None) -> dict[str, tuple[str, ...]]:
    if not url:
        return {}
    parsed = parse_qs(urlparse(url).query)
    keys = {
        "tag", "aff", "affid", "aff_id", "affiliate", "affiliate_id",
        "ref", "refid", "ref_id", "partner", "partner_id", "campid",
        "campaign", "subid", "sub_id", "clickid", "click_id",
    }
    return {
        key: tuple(values)
        for key, values in parsed.items()
        if key.lower() in keys
    }


def _offer_signature(page: dict) -> list[dict]:
    commerce = page.get("commerce") or {}
    normalized = []
    for offer in commerce.get("offers", [])[:20]:
        normalized.append({
            "price": offer.get("price"),
            "high_price": offer.get("high_price"),
            "currency": offer.get("currency"),
            "availability": offer.get("availability"),
            "url": offer.get("url"),
            "seller": offer.get("seller"),
        })
    return normalized


def snapshot_from_report(report: dict) -> dict:
    links = {}
    for chk in report.get("link_checks", []):
        key = f"{chk.get('page','')}|{chk.get('url','')}"
        links[key] = {
            "page": chk.get("page"),
            "url": chk.get("url"),
            "final_url": chk.get("final_url"),
            "final_status": chk.get("final_status"),
            "redirect_hops": len(chk.get("chain", [])),
            "is_affiliate": bool(chk.get("is_affiliate")),
            "is_cta": bool(chk.get("is_cta")),
            "anchor_text": chk.get("anchor_text", ""),
            "tracking_original": _tracking(chk.get("url")),
            "tracking_final": _tracking(chk.get("final_url")),
        }

    findings = {}
    for finding in report.get("findings", []):
        key = f"{finding.get('page','')}|{finding.get('url','')}|{finding.get('issue_type','')}"
        findings[key] = {
            "issue_type": finding.get("issue_type"),
            "severity": finding.get("severity"),
            "confidence": finding.get("confidence"),
            "revenue_risk_score": finding.get("revenue_risk_score"),
            "page": finding.get("page"),
            "url": finding.get("url"),
            "finding": finding.get("finding"),
        }

    pages = {}
    for page in report.get("pages", []):
        pages[page.get("page", "")] = {
            "status": page.get("status"),
            "final_url": page.get("final_url"),
            "commerce_offers": _offer_signature(page),
        }

    return {
        "captured_at": time.time(),
        "site": report.get("site"),
        "base": report.get("base"),
        "links": links,
        "findings": findings,
        "pages": pages,
    }


def _event(event_type: str, severity: str, **payload) -> dict:
    return {
        "event_type": event_type,
        "severity": severity,
        "detected_at": time.time(),
        **payload,
    }


def diff_snapshots(previous: dict, current: dict) -> list[dict]:
    changes: list[dict] = []

    old_links = previous.get("links", {})
    new_links = current.get("links", {})
    for key, new in new_links.items():
        old = old_links.get(key)
        if not old:
            continue

        if old.get("final_url") != new.get("final_url"):
            changes.append(_event(
                "DESTINATION_CHANGED",
                "high" if new.get("is_affiliate") or new.get("is_cta") else "medium",
                page=new.get("page"),
                url=new.get("url"),
                before=old.get("final_url"),
                after=new.get("final_url"),
            ))

        if old.get("final_status") != new.get("final_status"):
            changes.append(_event(
                "DESTINATION_STATUS_CHANGED",
                "high" if (new.get("final_status") or 0) >= 400 else "medium",
                page=new.get("page"),
                url=new.get("url"),
                before=old.get("final_status"),
                after=new.get("final_status"),
            ))

        old_tracking = old.get("tracking_final", {})
        new_tracking = new.get("tracking_final", {})
        dropped = sorted(k for k in old_tracking if k not in new_tracking)
        if dropped:
            changes.append(_event(
                "TRACKING_DROPPED",
                "critical" if new.get("is_affiliate") else "high",
                page=new.get("page"),
                url=new.get("url"),
                dropped_parameters=dropped,
                before=old_tracking,
                after=new_tracking,
            ))

    old_findings = previous.get("findings", {})
    new_findings = current.get("findings", {})
    for key, finding in new_findings.items():
        if key not in old_findings:
            changes.append(_event(
                "NEW_REVENUE_RISK",
                finding.get("severity") or "high",
                finding=finding,
            ))
    for key, finding in old_findings.items():
        if key not in new_findings:
            changes.append(_event(
                "REVENUE_RISK_RESOLVED",
                "info",
                finding=finding,
            ))

    old_pages = previous.get("pages", {})
    new_pages = current.get("pages", {})
    for page_url, new_page in new_pages.items():
        old_page = old_pages.get(page_url)
        if not old_page:
            continue
        old_offers = old_page.get("commerce_offers", [])
        new_offers = new_page.get("commerce_offers", [])
        if old_offers != new_offers and (old_offers or new_offers):
            changes.append(_event(
                "OFFER_DATA_CHANGED",
                "medium",
                page=page_url,
                before=old_offers,
                after=new_offers,
            ))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    changes.sort(key=lambda item: order.get(item.get("severity", "info"), 9))
    return changes


def create_monitor(
    site_name: str,
    base_url: str,
    *,
    max_pages: int = 8,
    cadence_hours: int = 24,
) -> dict:
    validate_public_http_url(base_url)
    monitor_id = str(uuid.uuid4())
    monitor = {
        "ok": True,
        "monitor_id": monitor_id,
        "site_name": site_name,
        "base_url": base_url,
        "max_pages": max(1, min(50, int(max_pages))),
        "cadence_hours": max(1, int(cadence_hours)),
        "created_at": time.time(),
        "last_run_at": None,
        "baseline": None,
        "last_changes": [],
        "history": [],
    }
    _path(monitor_id).write_text(json.dumps(monitor, indent=2))
    return monitor


def get_monitor(monitor_id: str) -> dict:
    path = _path(monitor_id)
    if not path.exists():
        return {"ok": False, "error": "monitor not found", "monitor_id": monitor_id}
    return json.loads(path.read_text())


def run_monitor(monitor_id: str) -> dict:
    monitor = get_monitor(monitor_id)
    if not monitor.get("ok"):
        return monitor

    report, report_path = run_audit(
        monitor["site_name"],
        monitor["base_url"],
        n_pages=monitor["max_pages"],
    )
    snapshot = snapshot_from_report(report)
    previous = monitor.get("baseline")
    changes = diff_snapshots(previous, snapshot) if previous else []

    run = {
        "ran_at": time.time(),
        "report_path": report_path,
        "findings": len(report.get("findings", [])),
        "changes": changes,
    }
    monitor["baseline"] = snapshot
    monitor["last_run_at"] = run["ran_at"]
    monitor["last_changes"] = changes
    monitor["history"] = (monitor.get("history", []) + [run])[-20:]
    _path(monitor_id).write_text(json.dumps(monitor, indent=2))

    return {
        "ok": True,
        "monitor_id": monitor_id,
        "baseline_created": previous is None,
        "stats": {
            "pages": len(report.get("pages", [])),
            "links_checked": len(report.get("link_checks", [])),
            "findings": len(report.get("findings", [])),
            "changes": len(changes),
        },
        "changes": changes,
    }


def get_changes(monitor_id: str) -> dict:
    monitor = get_monitor(monitor_id)
    if not monitor.get("ok"):
        return monitor
    return {
        "ok": True,
        "monitor_id": monitor_id,
        "last_run_at": monitor.get("last_run_at"),
        "count": len(monitor.get("last_changes", [])),
        "changes": monitor.get("last_changes", []),
    }
