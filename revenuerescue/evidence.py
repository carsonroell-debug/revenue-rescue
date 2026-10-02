"""Evidence-first Revenue Rescue finding model.

The scanner should prove deterministic web failures and let the agent explain
them. This module enriches a confirmed verdict with machine-readable issue
type, severity, confidence, revenue-risk score, source context, and a concrete
next action. It deliberately does not estimate dollars lost.
"""
from __future__ import annotations

import hashlib
import re

from .intelligence import dropped_tracking_params, tracking_params

CTA_RE = re.compile(
    r"\b(buy|shop|order|purchase|book|subscribe|sign[ -]?up|get started|"
    r"start free|view deal|see deal|check price|see price|claim|download)\b",
    re.I,
)


def looks_like_cta(anchor_text: str = "", class_text: str = "", role: str = "") -> bool:
    joined = f"{anchor_text} {class_text} {role}".strip()
    return bool(
        CTA_RE.search(joined)
        or re.search(r"\b(btn|button|cta)\b", class_text or "", re.I)
        or (role or "").lower() == "button"
    )


def tracking_evidence(original_url: str, final_url: str | None) -> dict:
    original = tracking_params(original_url)
    final = tracking_params(final_url or "")
    dropped = dropped_tracking_params(original_url, final_url)
    return {
        "original_tracking_params": sorted(original),
        "final_tracking_params": sorted(final),
        "dropped_tracking_params": dropped,
    }


def _classification(finding: str) -> tuple[str, str, float, int, str]:
    low = finding.lower()
    if "404" in low or "410" in low:
        return ("BROKEN_DESTINATION", "high", 0.99, 88, "Replace or remove the dead destination.")
    if "server error" in low:
        return ("DESTINATION_SERVER_ERROR", "high", 0.95, 78, "Verify the merchant destination and replace it if the failure persists.")
    if "soft 404" in low or "appears gone" in low:
        return ("PRODUCT_DESTINATION_GONE", "high", 0.93, 84, "Replace the destination with the current product or offer page.")
    if "redirect chain" in low:
        return ("REDIRECT_CHAIN", "medium", 0.96, 52, "Link directly to the final healthy destination when attribution allows.")
    if "tracking parameter dropped" in low:
        return (
            "AFFILIATE_TRACKING_DROPPED",
            "high",
            0.88,
            86,
            "Verify attribution through the redirect; regenerate or replace the URL if the parameter should persist.",
        )
    if "tracking" in low:
        return (
            "AFFILIATE_TRACKING_MISSING",
            "high",
            0.98,
            90,
            "Regenerate or replace the affiliate URL and verify attribution.",
        )
    if "structured offer marked discontinued" in low:
        return (
            "OFFER_DISCONTINUED",
            "high",
            0.98,
            84,
            "Update or remove the discontinued offer and its monetization path.",
        )
    if "homepage" in low:
        return ("DESTINATION_CHANGED", "high", 0.90, 76, "Verify the intended landing page and replace the stale URL.")
    return ("REVENUE_RISK", "medium", 0.80, 50, "Review the evidence and verify the destination.")


def _finding_id(page: str | None, url: str | None, issue_type: str) -> str:
    raw = f"{page or ''}|{url or ''}|{issue_type}".encode("utf-8")
    return "rr_" + hashlib.sha256(raw).hexdigest()[:16]


def build_finding(check: dict, finding: str) -> dict:
    issue_type, severity, confidence, score, recommendation = _classification(finding)
    is_affiliate = bool(check.get("is_affiliate"))
    is_cta = bool(check.get("is_cta"))
    commerce = check.get("commerce_context") or {}

    if is_affiliate:
        score += 5
    if is_cta:
        score += 7
    if commerce.get("has_product_schema"):
        score += 4
    if commerce.get("has_offer_schema"):
        score += 4
    score = min(100, score)

    if score >= 92:
        severity = "critical"
    elif score >= 72 and severity == "medium":
        severity = "high"

    evidence = {
        "final_status": check.get("final_status"),
        "redirect_hops": len(check.get("chain", [])),
        "redirect_chain": check.get("chain", []),
        "final_url": check.get("final_url"),
        "anchor_text": check.get("anchor_text", ""),
        "heading": check.get("heading", ""),
        "context": check.get("context", ""),
        "is_affiliate": is_affiliate,
        "is_cta": is_cta,
        "commerce": commerce,
    }
    evidence.update(tracking_evidence(check.get("url", ""), check.get("final_url")))

    return {
        "finding_id": _finding_id(check.get("page"), check.get("url"), issue_type),
        "issue_type": issue_type,
        "finding": finding,
        "severity": severity,
        "confidence": confidence,
        "revenue_risk_score": score,
        "page": check.get("page"),
        "url": check.get("url"),
        "final_url": check.get("final_url"),
        "is_affiliate": is_affiliate,
        "is_cta": is_cta,
        "evidence": evidence,
        "recommendation": recommendation,
    }
