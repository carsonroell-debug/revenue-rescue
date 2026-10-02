#!/usr/bin/env python3
"""Production HTTP surface for Revenue Rescue.

This module serves two interfaces from one ASGI process:

- MCP over Streamable HTTP at /mcp, implemented by FastMCP 4.
- REST/OpenAPI under /api/v1 for direct API clients and connector review.

The audit engine remains platform-neutral in revenuerescue.audit. Long-running
blocking crawl work is moved off the ASGI event loop with asyncio.to_thread so
the server can continue answering health checks and concurrent requests.

Set REVENUE_RESCUE_API_TOKEN to require a bearer token for MCP and audit REST
endpoints. Health and OpenAPI discovery remain public.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route

from .adapters.muse import MuseAdapter
from .audit import WORK_DIR
from .jobs import get_finding, get_findings as get_job_findings
from .jobs import get_job, start_audit_job
from .monitoring import create_monitor, get_changes, get_monitor, run_due_monitors, run_monitor
from .ops import allow_request, log_event, request_id
from .validation import ValidationError, validate_tool_args

ADAPTER = MuseAdapter()
API_TOKEN = os.environ.get("REVENUE_RESCUE_API_TOKEN", "").strip()
CRON_SECRET = os.environ.get("REVENUE_RESCUE_CRON_SECRET", "").strip()


def _build_mcp() -> FastMCP:
    auth = None
    if API_TOKEN:
        auth = StaticTokenVerifier(
            tokens={
                API_TOKEN: {
                    "sub": "revenue-rescue-user",
                    "client_id": "revenue-rescue-connector",
                }
            }
        )

    server = FastMCP(
        "Revenue Rescue",
        instructions=(
            "Use Revenue Rescue to audit publisher and commerce websites for "
            "confirmed revenue leaks such as dead affiliate destinations, "
            "tracking loss, soft-404 product redirects, and unhealthy redirect "
            "chains. Do not describe bot blocks or timeouts as confirmed leaks."
        ),
        auth=auth,
    )

    @server.tool
    async def audit_site(
        site_name: str,
        base_url: str,
        max_pages: int = 8,
    ) -> dict:
        """Audit a website for confirmed revenue leaks.

        Args:
            site_name: Human-readable site or business name.
            base_url: Public site root, including https://.
            max_pages: Number of likely monetized/review pages to inspect (1-12).
        """
        args = {
            "site_name": site_name,
            "base_url": base_url,
            "max_pages": max_pages,
        }
        return await asyncio.to_thread(ADAPTER.invoke, "audit_site", args)

    @server.tool
    async def start_audit(
        site_name: str,
        base_url: str,
        max_pages: int = 8,
    ) -> dict:
        """Start a background revenue-leak audit and return an audit_id immediately."""
        try:
            args = validate_tool_args("start_audit", {
                "site_name": site_name,
                "base_url": base_url,
                "max_pages": max_pages,
            })
            return start_audit_job(
                args["site_name"],
                args["base_url"],
                max_pages=args["max_pages"],
            )
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def get_audit_status(audit_id: str) -> dict:
        """Check whether a background audit is queued, running, completed, or failed."""
        try:
            return get_job(audit_id)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def get_findings(
        audit_id: str,
        severity: str | None = None,
        issue_type: str | None = None,
    ) -> dict:
        """Return completed findings, optionally filtered by severity or issue type."""
        try:
            return get_job_findings(audit_id, severity=severity, issue_type=issue_type)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def explain_finding(audit_id: str, finding_id: str) -> dict:
        """Explain one Revenue Rescue finding with its evidence and recommended action."""
        try:
            return get_finding(audit_id, finding_id)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def monitor_site(
        site_name: str,
        base_url: str,
        max_pages: int = 8,
        cadence_hours: int = 24,
    ) -> dict:
        """Create a persistent website revenue monitor.

        The first run establishes a baseline. Later runs emit only meaningful
        evidence changes such as tracking loss, destination changes, new
        findings, resolved findings, and structured offer changes.
        """
        try:
            args = validate_tool_args("monitor_site", {
                "site_name": site_name,
                "base_url": base_url,
                "max_pages": max_pages,
                "cadence_hours": cadence_hours,
            })
            return create_monitor(
                args["site_name"],
                args["base_url"],
                max_pages=args["max_pages"],
                cadence_hours=args["cadence_hours"],
            )
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def run_monitor_now(monitor_id: str) -> dict:
        """Run a monitor immediately and compare its evidence to the prior baseline."""
        return await asyncio.to_thread(run_monitor, monitor_id)

    @server.tool
    async def get_monitor_status(monitor_id: str) -> dict:
        """Return one monitor's configuration, latest run, and baseline metadata."""
        try:
            monitor = get_monitor(monitor_id)
            if not monitor.get("ok"):
                return monitor
            return {
                "ok": True,
                "monitor_id": monitor_id,
                "site_name": monitor.get("site_name"),
                "base_url": monitor.get("base_url"),
                "cadence_hours": monitor.get("cadence_hours"),
                "last_run_at": monitor.get("last_run_at"),
                "has_baseline": monitor.get("baseline") is not None,
                "last_change_count": len(monitor.get("last_changes", [])),
            }
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def get_monitor_changes(monitor_id: str) -> dict:
        """Return the latest evidence changes detected by a Revenue Rescue monitor."""
        try:
            return get_changes(monitor_id)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @server.tool
    async def list_audits() -> dict:
        """List recent Revenue Rescue audit reports available on this server."""
        return ADAPTER.invoke("list_audits", {})

    @server.tool
    async def get_audit(report_name: str) -> dict:
        """Load one previously completed audit report by its report filename."""
        try:
            return {"ok": True, "report": _load_report(report_name)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except FileNotFoundError:
            return {"ok": False, "error": "audit report not found"}

    @server.tool
    async def health_check() -> dict:
        """Check whether Revenue Rescue is online and ready for tool calls."""
        return {
            "ok": True,
            "service": "revenue-rescue",
            "mcp": "fastmcp-4",
            "auth_enabled": bool(API_TOKEN),
        }

    return server


def _valid_report_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9.\-_]*\.json", name, re.I))


def _load_report(name: str) -> dict:
    if not _valid_report_name(name):
        raise ValueError("invalid report filename")
    path = Path(WORK_DIR) / name
    if not path.exists():
        raise FileNotFoundError(name)
    return json.loads(path.read_text())


def _bearer_authorized(request: Request) -> bool:
    if not API_TOKEN:
        return True
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    provided = header[7:].strip()
    return secrets.compare_digest(provided, API_TOKEN)


def _auth_error() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "unauthorized"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def openapi_spec(server_url: str) -> dict:
    security = [{"bearerAuth": []}] if API_TOKEN else []

    def obj(properties=None, required=None):
        schema = {
            "type": "object",
            "properties": properties or {},
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        return schema

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Revenue Rescue",
            "version": "0.3.0",
            "description": (
                "Agent-native commerce observability: audits, evidence-backed "
                "findings, explanations, persistent monitors, and change detection."
            ),
        },
        "servers": [{"url": server_url.rstrip("/")}],
        "paths": {
            "/api/v1/jobs": {
                "post": {
                    "operationId": "startAudit",
                    "summary": "Start a background revenue audit",
                    "security": security,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": next(
                                    t["input_schema"]
                                    for t in ADAPTER.describe()["tools"]
                                    if t["name"] == "start_audit"
                                )
                            }
                        },
                    },
                    "responses": {"200": {"description": "Audit queued"}},
                }
            },
            "/api/v1/jobs/{audit_id}": {
                "get": {
                    "operationId": "getAuditStatus",
                    "summary": "Get audit job status",
                    "security": security,
                    "parameters": [{
                        "name": "audit_id", "in": "path", "required": True,
                        "schema": {"type": "string"}
                    }],
                    "responses": {"200": {"description": "Audit status"}},
                }
            },
            "/api/v1/jobs/{audit_id}/findings": {
                "get": {
                    "operationId": "getFindings",
                    "summary": "Get audit findings",
                    "security": security,
                    "parameters": [
                        {"name": "audit_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "severity", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "issue_type", "in": "query", "required": False, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "Findings"}},
                }
            },
            "/api/v1/jobs/{audit_id}/findings/{finding_id}": {
                "get": {
                    "operationId": "explainFinding",
                    "summary": "Explain one finding",
                    "security": security,
                    "parameters": [
                        {"name": "audit_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "finding_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "Finding explanation"}},
                }
            },
            "/api/v1/monitors": {
                "post": {
                    "operationId": "createMonitor",
                    "summary": "Create a persistent revenue monitor",
                    "security": security,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": next(
                                    t["input_schema"]
                                    for t in ADAPTER.describe()["tools"]
                                    if t["name"] == "monitor_site"
                                )
                            }
                        },
                    },
                    "responses": {"200": {"description": "Monitor created"}},
                }
            },
            "/api/v1/monitors/{monitor_id}": {
                "get": {
                    "operationId": "getMonitorStatus",
                    "summary": "Get monitor status",
                    "security": security,
                    "parameters": [{
                        "name": "monitor_id", "in": "path", "required": True,
                        "schema": {"type": "string"}
                    }],
                    "responses": {"200": {"description": "Monitor status"}},
                }
            },
            "/api/v1/monitors/{monitor_id}/run": {
                "post": {
                    "operationId": "runMonitorNow",
                    "summary": "Run a monitor immediately",
                    "security": security,
                    "parameters": [{
                        "name": "monitor_id", "in": "path", "required": True,
                        "schema": {"type": "string"}
                    }],
                    "responses": {"200": {"description": "Monitor result"}},
                }
            },
            "/api/v1/monitors/{monitor_id}/changes": {
                "get": {
                    "operationId": "getMonitorChanges",
                    "summary": "Get latest monitor changes",
                    "security": security,
                    "parameters": [{
                        "name": "monitor_id", "in": "path", "required": True,
                        "schema": {"type": "string"}
                    }],
                    "responses": {"200": {"description": "Detected changes"}},
                }
            },
            "/api/v1/audits": {
                "post": {
                    "operationId": "auditSite",
                    "summary": "Run a small synchronous audit",
                    "security": security,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": next(
                                    t["input_schema"]
                                    for t in ADAPTER.describe()["tools"]
                                    if t["name"] == "audit_site"
                                )
                            }
                        },
                    },
                    "responses": {"200": {"description": "Completed audit"}},
                }
            },
        },
    }
    if API_TOKEN:
        spec["components"] = {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque",
                }
            }
        }
    return spec


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "revenue-rescue",
            "version": "0.2.0",
            "mcp": "/mcp",
            "rest": "/api/v1/audits",
            "auth_enabled": bool(API_TOKEN),
        }
    )


async def openapi(request: Request) -> JSONResponse:
    return JSONResponse(openapi_spec(str(request.base_url)))


async def audits(request: Request) -> JSONResponse:
    rid = request.headers.get("x-request-id") or request_id()
    client = request.client.host if request.client else "unknown"
    if not allow_request(f"rest:{client}", limit=30, window_seconds=60):
        log_event("rate_limited", request_id=rid, client=client, path=str(request.url.path))
        return JSONResponse(
            {"ok": False, "error": "rate limit exceeded", "request_id": rid},
            status_code=429,
            headers={"X-Request-ID": rid, "Retry-After": "60"},
        )
    if not _bearer_authorized(request):
        log_event("unauthorized", request_id=rid, client=client, path=str(request.url.path))
        response = _auth_error()
        response.headers["X-Request-ID"] = rid
        return response
    log_event("request_started", request_id=rid, client=client, method=request.method, path=str(request.url.path))

    if request.method == "GET":
        return JSONResponse(ADAPTER.invoke("list_audits", {}))

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "request body must be valid JSON"},
            status_code=400,
        )

    out = await asyncio.to_thread(ADAPTER.invoke, "audit_site", body)
    log_event(
        "request_completed",
        request_id=rid,
        client=client,
        method=request.method,
        path=str(request.url.path),
        ok=bool(out.get("ok")),
    )
    return JSONResponse(
        {**out, "request_id": rid},
        status_code=200 if out.get("ok") else 400,
        headers={"X-Request-ID": rid},
    )


async def audit_report(request: Request) -> JSONResponse:
    if not _bearer_authorized(request):
        return _auth_error()

    name = request.path_params["report_name"]
    try:
        return JSONResponse({"ok": True, "report": _load_report(name)})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except FileNotFoundError:
        return JSONResponse(
            {"ok": False, "error": "audit report not found"},
            status_code=404,
        )


async def _authorized_json(request: Request) -> tuple[str, str] | JSONResponse:
    rid = request.headers.get("x-request-id") or request_id()
    client = request.client.host if request.client else "unknown"
    if not allow_request(f"rest:{client}", limit=60, window_seconds=60):
        return JSONResponse(
            {"ok": False, "error": "rate limit exceeded", "request_id": rid},
            status_code=429,
            headers={"X-Request-ID": rid, "Retry-After": "60"},
        )
    if not _bearer_authorized(request):
        response = _auth_error()
        response.headers["X-Request-ID"] = rid
        return response
    return rid, client


async def jobs_collection(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    try:
        body = await request.json()
        body = validate_tool_args("start_audit", body)
        out = start_audit_job(
            body["site_name"],
            body["base_url"],
            max_pages=body["max_pages"],
        )
    except Exception as exc:
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 400)


async def job_detail(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    out = get_job(request.path_params["audit_id"])
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 404)


async def job_findings(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    out = get_job_findings(
        request.path_params["audit_id"],
        severity=request.query_params.get("severity"),
        issue_type=request.query_params.get("issue_type"),
    )
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 404)


async def finding_detail(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    out = get_finding(
        request.path_params["audit_id"],
        request.path_params["finding_id"],
    )
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 404)


async def monitors_collection(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    try:
        body = await request.json()
        body = validate_tool_args("monitor_site", body)
        out = create_monitor(
            body["site_name"],
            body["base_url"],
            max_pages=body["max_pages"],
            cadence_hours=body["cadence_hours"],
        )
    except Exception as exc:
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 400)


async def monitor_detail(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    monitor = get_monitor(request.path_params["monitor_id"])
    if not monitor.get("ok"):
        return JSONResponse({**monitor, "request_id": rid}, status_code=404)
    out = {
        "ok": True,
        "monitor_id": monitor.get("monitor_id"),
        "site_name": monitor.get("site_name"),
        "base_url": monitor.get("base_url"),
        "cadence_hours": monitor.get("cadence_hours"),
        "last_run_at": monitor.get("last_run_at"),
        "has_baseline": monitor.get("baseline") is not None,
        "last_change_count": len(monitor.get("last_changes", [])),
    }
    return JSONResponse({**out, "request_id": rid})


async def monitor_run(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    out = await asyncio.to_thread(run_monitor, request.path_params["monitor_id"])
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 404)


async def monitor_changes(request: Request) -> JSONResponse:
    auth = await _authorized_json(request)
    if isinstance(auth, JSONResponse):
        return auth
    rid, _client = auth
    out = get_changes(request.path_params["monitor_id"])
    return JSONResponse({**out, "request_id": rid}, status_code=200 if out.get("ok") else 404)


async def cron_due_monitors(request: Request) -> JSONResponse:
    rid = request.headers.get("x-request-id") or request_id()
    if not CRON_SECRET:
        return JSONResponse(
            {"ok": False, "error": "cron is not configured", "request_id": rid},
            status_code=503,
            headers={"X-Request-ID": rid},
        )
    header = request.headers.get("authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not supplied or not secrets.compare_digest(supplied, CRON_SECRET):
        log_event("cron_unauthorized", request_id=rid)
        return JSONResponse(
            {"ok": False, "error": "unauthorized", "request_id": rid},
            status_code=401,
            headers={"X-Request-ID": rid},
        )

    result = await asyncio.to_thread(run_due_monitors, limit=5)
    log_event(
        "cron_due_monitors_completed",
        request_id=rid,
        due_count=result.get("due_count"),
        ran_count=result.get("ran_count"),
    )
    return JSONResponse(
        {**result, "request_id": rid},
        headers={"X-Request-ID": rid},
    )


async def homepage(_: Request) -> HTMLResponse:
    return HTMLResponse(
        "<html><body><h1>Revenue Rescue</h1>"
        "<p>Agent-native revenue leak auditing.</p>"
        "<ul>"
        "<li>MCP: <code>/mcp</code></li>"
        "<li>REST: <code>/api/v1/audits</code></li>"
        "<li>OpenAPI: <code>/api/v1/openapi.json</code></li>"
        "<li>Health: <code>/health</code></li>"
        "</ul></body></html>"
    )


MCP = _build_mcp()
MCP_APP = MCP.http_app(path="/mcp")

app = Starlette(
    routes=[
        Route("/", homepage, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
        Route("/api/v1/openapi.json", openapi, methods=["GET"]),
        Route("/api/v1/audits", audits, methods=["GET", "POST"]),
        Route("/api/v1/audits/{report_name}", audit_report, methods=["GET"]),
        Route("/api/v1/jobs", jobs_collection, methods=["POST"]),
        Route("/api/v1/jobs/{audit_id}", job_detail, methods=["GET"]),
        Route("/api/v1/jobs/{audit_id}/findings", job_findings, methods=["GET"]),
        Route("/api/v1/jobs/{audit_id}/findings/{finding_id}", finding_detail, methods=["GET"]),
        Route("/api/v1/monitors", monitors_collection, methods=["POST"]),
        Route("/api/v1/monitors/{monitor_id}", monitor_detail, methods=["GET"]),
        Route("/api/v1/monitors/{monitor_id}/run", monitor_run, methods=["POST"]),
        Route("/api/v1/monitors/{monitor_id}/changes", monitor_changes, methods=["GET"]),
        Route("/internal/cron/due-monitors", cron_due_monitors, methods=["POST"]),
        Mount("/", app=MCP_APP),
    ],
    lifespan=MCP_APP.lifespan,
)


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8787"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
