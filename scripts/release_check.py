#!/usr/bin/env python3
"""Offline release preflight for Revenue Rescue."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from revenuerescue.adapters.muse import MuseAdapter
from revenuerescue.config import RuntimeConfig
from revenuerescue.server import openapi_spec
from revenuerescue.version import __version__


def check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> None:
    failures: list[str] = []

    check(bool(__version__) and __version__.count(".") == 2, "invalid semantic version", failures)

    required_files = [
        "SECURITY.md",
        "docs/threat-model.md",
        "docs/postgres_schema.sql",
        "submission/privacy_policy.md",
        "submission/terms_of_service.md",
        "benchmarks/README.md",
    ]
    for rel in required_files:
        check((ROOT / rel).exists(), f"missing release file: {rel}", failures)

    tools = MuseAdapter().describe()["tools"]
    names = {item["name"] for item in tools}
    required_tools = {
        "start_audit",
        "get_audit_status",
        "get_findings",
        "explain_finding",
        "monitor_site",
        "run_monitor_now",
        "get_monitor_status",
        "get_monitor_changes",
    }
    check(required_tools.issubset(names), "canonical tool surface is incomplete", failures)

    spec = openapi_spec("https://example.invalid/")
    operation_ids = {
        op["operationId"]
        for path in spec["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    }
    check(
        {
            "startAudit",
            "getAuditStatus",
            "getFindings",
            "explainFinding",
            "createMonitor",
            "getMonitorStatus",
            "runMonitorNow",
            "getMonitorChanges",
        }.issubset(operation_ids),
        "OpenAPI surface is incomplete",
        failures,
    )

    production_example = RuntimeConfig(
        environment="production",
        api_token="configured",
        cron_secret="configured",
        database_url="postgresql://configured",
        scrapling_enabled=True,
        port=8787,
    )
    check(not production_example.problems(), "production config validation is inconsistent", failures)

    result = {
        "ok": not failures,
        "version": __version__,
        "tools": len(tools),
        "openapi_operations": len(operation_ids),
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
