"""Canonical Revenue Rescue agent tool contracts.

Platform adapters should translate this contract, not redefine product behavior.
Keep tool names and schemas stable across MCP, REST/OpenAPI, Muse-style connector
metadata, and other agent platforms.
"""
from __future__ import annotations

AUDIT_INPUT = {
    "type": "object",
    "properties": {
        "site_name": {
            "type": "string",
            "minLength": 1,
            "description": "Human-readable site or business name.",
        },
        "base_url": {
            "type": "string",
            "format": "uri",
            "description": "Public HTTP(S) site root.",
        },
        "max_pages": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 8,
        },
    },
    "required": ["site_name", "base_url"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "audit_site",
        "description": (
            "Run a small synchronous audit for confirmed website revenue risks. "
            "Use start_audit for larger or slower scans."
        ),
        "input_schema": AUDIT_INPUT,
    },
    {
        "name": "start_audit",
        "description": (
            "Start a background website revenue audit and return an audit_id immediately."
        ),
        "input_schema": AUDIT_INPUT,
    },
    {
        "name": "get_audit_status",
        "description": "Check whether a background audit is queued, running, completed, or failed.",
        "input_schema": {
            "type": "object",
            "properties": {"audit_id": {"type": "string"}},
            "required": ["audit_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_findings",
        "description": "Return completed findings, optionally filtered by severity or issue type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "info"],
                },
                "issue_type": {"type": "string"},
            },
            "required": ["audit_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "explain_finding",
        "description": (
            "Explain one finding using its stored evidence and return the recommended action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string"},
                "finding_id": {"type": "string"},
            },
            "required": ["audit_id", "finding_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "monitor_site",
        "description": (
            "Create a persistent monitor. The first run establishes a baseline; "
            "later runs detect deterministic revenue-impacting changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "site_name": {"type": "string", "minLength": 1},
                "base_url": {"type": "string", "format": "uri"},
                "max_pages": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 8,
                },
                "cadence_hours": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 720,
                    "default": 24,
                },
            },
            "required": ["site_name", "base_url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_monitor_now",
        "description": "Run one monitor now and compare the result with its previous baseline.",
        "input_schema": {
            "type": "object",
            "properties": {"monitor_id": {"type": "string"}},
            "required": ["monitor_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_monitor_status",
        "description": "Return monitor configuration and latest-run metadata.",
        "input_schema": {
            "type": "object",
            "properties": {"monitor_id": {"type": "string"}},
            "required": ["monitor_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_monitor_changes",
        "description": "Return the latest deterministic changes detected by a monitor.",
        "input_schema": {
            "type": "object",
            "properties": {"monitor_id": {"type": "string"}},
            "required": ["monitor_id"],
            "additionalProperties": False,
        },
    },
]


def tool(name: str) -> dict:
    for item in TOOLS:
        if item["name"] == name:
            return item
    raise KeyError(name)
