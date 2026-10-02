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
from .jobs import get_findings as get_job_findings
from .jobs import get_job, start_audit_job
from .monitoring import create_monitor, get_changes, get_monitor, run_monitor

ADAPTER = MuseAdapter()
API_TOKEN = os.environ.get("REVENUE_RESCUE_API_TOKEN", "").strip()


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
            return start_audit_job(site_name, base_url, max_pages=max_pages)
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
            return create_monitor(
                site_name,
                base_url,
                max_pages=max_pages,
                cadence_hours=cadence_hours,
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
    desc = ADAPTER.describe()
    audit_schema = desc["tools"][0]["input_schema"]
    security = [{"bearerAuth": []}] if API_TOKEN else []
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Revenue Rescue",
            "version": "0.2.0",
            "description": (
                "Agent-native website revenue-leak auditing. Returns confirmed "
                "evidence for broken affiliate destinations, tracking loss, "
                "soft-404 product redirects, and unhealthy redirect chains."
            ),
        },
        "servers": [{"url": server_url.rstrip("/")}],
        "paths": {
            "/api/v1/audits": {
                "post": {
                    "operationId": "auditSite",
                    "summary": "Run a revenue-leak audit",
                    "security": security,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": audit_schema}},
                    },
                    "responses": {
                        "200": {
                            "description": "Completed audit",
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            },
                        },
                        "400": {"description": "Bad request"},
                        "401": {"description": "Unauthorized"},
                    },
                },
                "get": {
                    "operationId": "listAudits",
                    "summary": "List recent audit reports",
                    "security": security,
                    "responses": {
                        "200": {"description": "Recent audit report filenames"},
                        "401": {"description": "Unauthorized"},
                    },
                },
            },
            "/api/v1/audits/{report_name}": {
                "get": {
                    "operationId": "getAudit",
                    "summary": "Fetch a completed audit report",
                    "security": security,
                    "parameters": [
                        {
                            "name": "report_name",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {"description": "Audit report"},
                        "400": {"description": "Invalid report name"},
                        "401": {"description": "Unauthorized"},
                        "404": {"description": "Audit not found"},
                    },
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
    if not _bearer_authorized(request):
        return _auth_error()

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
    return JSONResponse(out, status_code=200 if out.get("ok") else 400)


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
