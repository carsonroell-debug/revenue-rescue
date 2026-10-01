#!/usr/bin/env python3
"""Revenue Rescue server: one process, two agent-facing surfaces.

  POST /mcp                    MCP streamable-HTTP endpoint (JSON-RPC 2.0):
                               initialize, tools/list, tools/call.
                               This is the "Existing MCP" submission path.
  POST /api/v1/audits          Run an audit synchronously; returns the report.
  GET  /api/v1/audits          List stored audit reports.
  GET  /api/v1/audits/<name>   Fetch one stored report.
  GET  /api/v1/openapi.json    OpenAPI 3.0 spec for this API
                               ("Raw API" submission path).
  GET  /health                  {"ok": true}

Both surfaces delegate to revenuerescue.adapters.muse.MuseAdapter, so the tool
contract (audit_site / list_audits) is identical on both paths.

Run:  venv/bin/python -m revenuerescue.server [--port 8787]
"""
import json
import sys
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
from pathlib import Path

from .adapters.muse import MuseAdapter
from .audit import WORK_DIR

MCP_PROTOCOL = "2025-06-18"

ADAPTER = MuseAdapter()


def _json(obj, status=200):
    body = json.dumps(obj).encode()
    return status, [("Content-Type", "application/json"),
                    ("Content-Length", str(len(body)))], body


def handle_mcp_rpc(req):
    """Minimal MCP streamable-HTTP handler (single JSON response per request)."""
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params", {}) or {}

    def result(payload):
        return {"jsonrpc": "2.0", "id": rid, "result": payload}

    def error(code, message):
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": code, "message": message}}

    if method == "initialize":
        return result({
            "protocolVersion": params.get("protocolVersion", MCP_PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "revenue-rescue", "version": "0.1.0"},
        })
    if method == "notifications/initialized":
        return None  # notification: no response
    if method == "tools/list":
        desc = ADAPTER.describe()
        return result({"tools": [
            {"name": t["name"], "description": t["description"],
             "inputSchema": t["input_schema"]} for t in desc["tools"]]})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        out = ADAPTER.invoke(name, args)
        text = out.get("summary") if out.get("ok") else f"Error: {out.get('error')}"
        return result({"content": [{"type": "text", "text": text}],
                       "structuredContent": out,
                       "isError": not out.get("ok", False)})
    if method == "ping":
        return result({})
    return error(-32601, f"method not found: {method}")


def openapi_spec(host_port):
    desc = ADAPTER.describe()
    props = desc["tools"][0]["input_schema"]
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Revenue Rescue",
            "version": "0.1.0",
            "description": ("Audit a publisher website for revenue leaks: dead "
                            "affiliate links, missing tracking parameters, and "
                            "soft-404 product redirects. Confirmed findings only."),
        },
        "servers": [{"url": f"http://{host_port}"}],
        "paths": {
            "/api/v1/audits": {
                "post": {
                    "operationId": "auditSite",
                    "summary": "Run a revenue-leak audit on a site",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": props}},
                    },
                    "responses": {
                        "200": {"description": "Audit report",
                                "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Bad request"},
                    },
                },
                "get": {
                    "operationId": "listAudits",
                    "summary": "List recent audit reports",
                    "responses": {"200": {"description": "List of report filenames"}},
                },
            },
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "RevenueRescue/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("server: " + fmt % args + "\n")

    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._send(*_json({"ok": True, "service": "revenue-rescue"}))
        elif path == "/api/v1/openapi.json":
            host = self.headers.get("Host", "localhost:8787")
            self._send(*_json(openapi_spec(host)))
        elif path == "/api/v1/audits":
            out = ADAPTER.invoke("list_audits", {})
            self._send(*_json(out))
        elif path.startswith("/api/v1/audits/"):
            name = unquote(path.rsplit("/", 1)[1])
            if not re.fullmatch(r"[a-z0-9][a-z0-9.\-_]*\.json", name, re.I):
                self._send(*_json({"ok": False, "error": "bad filename"}, 400))
                return
            fp = WORK_DIR / name
            if not fp.exists():
                self._send(*_json({"ok": False, "error": "not found"}, 404))
                return
            self._send(*_json(json.loads(fp.read_text())))
        elif path == "/":
            html = (b"<html><body><h1>Revenue Rescue</h1>"
                    b"<p>Audit API + MCP endpoint. See /api/v1/openapi.json and POST /mcp.</p>"
                    b"</body></html>")
            self._send(200, [("Content-Type", "text/html"),
                             ("Content-Length", str(len(html)))], html)
        else:
            self._send(*_json({"ok": False, "error": "not found"}, 404))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/mcp":
            req = self._read_json()
            resp = handle_mcp_rpc(req)
            if resp is None:
                self.send_response(202)
                self.end_headers()
                return
            self._send(*_json(resp))
        elif path == "/api/v1/audits":
            body = self._read_json()
            out = ADAPTER.invoke("audit_site", body)
            self._send(*_json(out, 200 if out.get("ok") else 400))
        else:
            self._send(*_json({"ok": False, "error": "not found"}, 404))


def main():
    port = 8787
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Revenue Rescue listening on http://127.0.0.1:{port} "
          f"(REST /api/v1, MCP POST /mcp, OpenAPI /api/v1/openapi.json)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
