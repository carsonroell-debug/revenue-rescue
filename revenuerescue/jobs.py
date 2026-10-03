"""Background audit jobs for agent-friendly long-running scans.

This is a durable-on-disk bridge between synchronous prototype scans and the
future Postgres/Supabase queue. Job metadata survives process restarts, while
active execution is handled by a bounded thread pool.

Production horizontal scaling should replace this backend with Postgres +
a real worker queue without changing the MCP tool contract.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import WORK_DIR, run_audit
from .ops import log_event
from .security import validate_public_http_url
from .storage import get_state, list_state, put_state

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="revenue-audit")
_LOCK = threading.Lock()

# A job still sitting in queued/running with no progress past this age is
# assumed orphaned (worker died mid-run, or the process died between the
# queue write and executor pickup). Tunable; injectable in tests.
ORPHAN_JOB_THRESHOLD_SECONDS = 30 * 60


def _validate_id(audit_id: str) -> str:
    if not audit_id or any(ch not in "0123456789abcdef-" for ch in audit_id.lower()):
        raise ValueError("invalid audit id")
    return audit_id


def _write_job(job: dict) -> None:
    put_state("audit_jobs", _validate_id(job["audit_id"]), job)


def reap_orphaned_jobs(
    *,
    now: float | None = None,
    threshold_seconds: float = ORPHAN_JOB_THRESHOLD_SECONDS,
) -> dict:
    """Release jobs stuck in queued/running past the staleness threshold.

    Crash recovery: if a worker thread dies mid-run (or the process dies
    between the queue write and the executor pickup), the job would sit in
    ``queued``/``running`` forever. The reaper marks such jobs ``failed``
    with a clear reason so nothing wedges silently. No new states are
    introduced; a reaped job is honest about what happened and the caller
    can simply start a fresh audit.

    Staleness is measured from ``started_at`` for running jobs and
    ``created_at`` for queued jobs. Jobs with a missing timestamp are
    treated as orphaned (a partial/corrupt write can never make progress).
    Every reaped job is logged via ``log_event``.
    """
    current = time.time() if now is None else now
    reaped: list[str] = []
    with _LOCK:
        for job in list_state("audit_jobs"):
            status = job.get("status")
            if status == "running":
                stamp = job.get("started_at")
            elif status == "queued":
                stamp = job.get("created_at")
            else:
                continue
            age = None if stamp is None else current - stamp
            if age is not None and age < threshold_seconds:
                continue
            audit_id = job.get("audit_id")
            age_desc = "unknown duration" if age is None else f"{age:.0f}s"
            job.update(
                {
                    "ok": False,
                    "status": "failed",
                    "completed_at": current,
                    "error": (
                        f"orphaned: stuck in {status!r} for {age_desc} with no "
                        f"progress (worker likely died); reaped after "
                        f"{threshold_seconds:.0f}s staleness threshold"
                    ),
                }
            )
            _write_job(job)
            log_event(
                "job_reaped",
                audit_id=audit_id,
                prior_status=status,
                age_seconds=None if age is None else round(age, 1),
            )
            reaped.append(audit_id)
    return {"ok": True, "reaped": len(reaped), "audit_ids": reaped}


def get_job(audit_id: str) -> dict:
    audit_id = _validate_id(audit_id)
    job = get_state("audit_jobs", audit_id)
    if job is None:
        return {"ok": False, "error": "audit not found", "audit_id": audit_id}
    return job


def _run_job(job: dict) -> None:
    job["status"] = "running"
    job["started_at"] = time.time()
    with _LOCK:
        _write_job(job)

    try:
        report, report_path = run_audit(
            job["site_name"],
            job["base_url"],
            n_pages=job["max_pages"],
        )
        job.update(
            {
                "ok": True,
                "status": "completed",
                "completed_at": time.time(),
                "report_path": report_path,
                "stats": {
                    "pages": len(report.get("pages", [])),
                    "links_checked": len(report.get("link_checks", [])),
                    "findings": len(report.get("findings", [])),
                },
                "findings": report.get("findings", []),
            }
        )
    except Exception as exc:
        job.update(
            {
                "ok": False,
                "status": "failed",
                "completed_at": time.time(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    with _LOCK:
        _write_job(job)


def start_audit_job(
    site_name: str,
    base_url: str,
    max_pages: int = 8,
) -> dict:
    validate_public_http_url(base_url)
    max_pages = max(1, min(50, int(max_pages)))
    audit_id = str(uuid.uuid4())
    now = time.time()
    job = {
        "ok": True,
        "audit_id": audit_id,
        "status": "queued",
        "site_name": site_name,
        "base_url": base_url,
        "max_pages": max_pages,
        "created_at": now,
    }
    with _LOCK:
        _write_job(job)
    _EXECUTOR.submit(_run_job, dict(job))
    return job


def get_findings(audit_id: str, severity: str | None = None, issue_type: str | None = None) -> dict:
    job = get_job(audit_id)
    if not job.get("ok") or job.get("status") != "completed":
        return job

    findings = job.get("findings", [])
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]
    if issue_type:
        findings = [f for f in findings if f.get("issue_type") == issue_type]
    return {
        "ok": True,
        "audit_id": audit_id,
        "status": "completed",
        "count": len(findings),
        "findings": findings,
    }


def get_finding(audit_id: str, finding_id: str) -> dict:
    """Return one finding with evidence and a concise agent explanation."""
    job = get_job(audit_id)
    if not job.get("ok") or job.get("status") != "completed":
        return job
    for finding in job.get("findings", []):
        if finding.get("finding_id") == finding_id:
            evidence = finding.get("evidence") or {}
            why = [
                finding.get("finding", "Confirmed revenue risk."),
                f"Severity: {finding.get('severity', 'unknown')}.",
                f"Confidence: {finding.get('confidence', 'unknown')}.",
                f"Revenue risk score: {finding.get('revenue_risk_score', 'unknown')}/100.",
            ]
            if evidence.get("anchor_text"):
                why.append(f"CTA/link text: {evidence['anchor_text']}.")
            if evidence.get("dropped_tracking_params"):
                why.append(
                    "Dropped tracking parameters: "
                    + ", ".join(evidence["dropped_tracking_params"])
                    + "."
                )
            return {
                "ok": True,
                "audit_id": audit_id,
                "finding": finding,
                "explanation": " ".join(why),
                "recommended_action": finding.get("recommendation"),
            }
    return {
        "ok": False,
        "audit_id": audit_id,
        "finding_id": finding_id,
        "error": "finding not found",
    }
