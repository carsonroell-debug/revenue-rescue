"""Durable state backend for Revenue Rescue.

If DATABASE_URL (or SUPABASE_DB_URL) is configured, state is stored in a
private Postgres schema. Otherwise development falls back to local JSON files.

The state API is intentionally tiny so the backend can later move to a queue,
ORM, or managed service without changing jobs/monitoring contracts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "work" / "state"
try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Read-only serverless filesystem: state falls back to unavailable;
    # storage_health() already reports this gracefully at runtime.
    pass

DATABASE_URL = (
    os.environ.get("DATABASE_URL", "").strip()
    or os.environ.get("SUPABASE_DB_URL", "").strip()
)

# Retention policy: completed audit reports are ephemeral working data, not a
# permanent archive. Anything older than this is pruned by the cron endpoint.
DEFAULT_RETENTION_DAYS = 90


def using_postgres() -> bool:
    return bool(DATABASE_URL)


def _local_path(kind: str, key: str) -> Path:
    safe_kind = "".join(ch for ch in kind.lower() if ch.isalnum() or ch in "_-")
    safe_key = "".join(ch for ch in key.lower() if ch.isalnum() or ch in "_-")
    if not safe_kind or not safe_key:
        raise ValueError("invalid state key")
    folder = STATE_DIR / safe_kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{safe_key}.json"


def _table(kind: str) -> str:
    mapping = {
        "audit_jobs": "revenue_rescue.audit_jobs",
        "monitors": "revenue_rescue.monitors",
    }
    try:
        return mapping[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported state kind: {kind}") from exc


def put_state(kind: str, key: str, state: dict[str, Any]) -> None:
    if not using_postgres():
        path = _local_path(kind, key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(path)
        return

    table = _table(kind)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into {table} (id, state, updated_at)
                values (%s::uuid, %s, now())
                on conflict (id)
                do update set state = excluded.state, updated_at = now()
                """,
                (key, Jsonb(state)),
            )


def get_state(kind: str, key: str) -> dict[str, Any] | None:
    if not using_postgres():
        path = _local_path(kind, key)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    table = _table(kind)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select state from {table} where id = %s::uuid", (key,))
            row = cur.fetchone()
            if not row:
                return None
            return row[0]


def delete_state(kind: str, key: str) -> bool:
    if not using_postgres():
        path = _local_path(kind, key)
        if not path.exists():
            return False
        path.unlink()
        return True

    table = _table(kind)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"delete from {table} where id = %s::uuid", (key,))
            return cur.rowcount > 0


def prune_states_older_than(kind: str, max_age_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete state objects older than max_age_days. Returns count deleted.

    Only audit job records are pruned (ephemeral working data). Monitor
    configurations are user-owned recurring watches and are never pruned here.
    """
    import time

    if kind != "audit_jobs":
        raise ValueError("retention pruning applies to audit_jobs only")
    cutoff = time.time() - max_age_days * 86400
    if not using_postgres():
        folder = STATE_DIR / "".join(ch for ch in kind.lower() if ch.isalnum() or ch in "_-")
        if not folder.exists():
            return 0
        deleted = 0
        for path in folder.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
            except OSError:
                continue
        return deleted

    table = _table(kind)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"delete from {table} where updated_at < now() - make_interval(days => %s)",
                (max_age_days,),
            )
            return cur.rowcount


def list_state(kind: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """List stored state objects for one supported kind, newest first."""
    limit = max(1, min(1000, int(limit)))
    if not using_postgres():
        folder = STATE_DIR / "".join(ch for ch in kind.lower() if ch.isalnum() or ch in "_-")
        if not folder.exists():
            return []
        rows = []
        for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                rows.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return rows

    table = _table(kind)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select state from {table} order by updated_at desc limit %s", (limit,))
            return [row[0] for row in cur.fetchall()]


def storage_health() -> dict:
    """Check whether the configured state backend is usable."""
    if not using_postgres():
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            probe = STATE_DIR / ".healthcheck"
            probe.write_text("ok")
            probe.unlink(missing_ok=True)
            return {"ok": True, "backend": "local-json"}
        except OSError as exc:
            return {"ok": False, "backend": "local-json", "error": str(exc)}

    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                row = cur.fetchone()
                if not row or row[0] != 1:
                    return {"ok": False, "backend": "postgres", "error": "unexpected database probe result"}
        return {"ok": True, "backend": "postgres"}
    except Exception as exc:
        return {"ok": False, "backend": "postgres", "error": f"{type(exc).__name__}: {exc}"}
