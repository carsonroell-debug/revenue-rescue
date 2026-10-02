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
STATE_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = (
    os.environ.get("DATABASE_URL", "").strip()
    or os.environ.get("SUPABASE_DB_URL", "").strip()
)


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
