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
from .security import validate_public_http_url

JOB_DIR = WORK_DIR / "jobs"
JOB_DIR.mkdir(parents=True, exist_ok=True)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="revenue-audit")
_LOCK = threading.Lock()


def _job_path(audit_id: str) -> Path:
    if not audit_id or any(ch not in "0123456789abcdef-" for ch in audit_id.lower()):
        raise ValueError("invalid audit id")
    return JOB_DIR / f"{audit_id}.json"


def _write_job(job: dict) -> None:
    path = _job_path(job["audit_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2))
    tmp.replace(path)


def get_job(audit_id: str) -> dict:
    path = _job_path(audit_id)
    if not path.exists():
        return {"ok": False, "error": "audit not found", "audit_id": audit_id}
    return json.loads(path.read_text())


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
