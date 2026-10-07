# Revenue Rescue — Architecture

**Implementation:** `revenuerescue/` · ~3,100 LOC · Python 3.12
**Entry point:** `revenuerescue/server.py` → `main()` → `uvicorn` (ASGI).

## Layers

```
                    ┌─────────────────────────────┐
                    │        server.py (ASGI)       │
                    │  Starlette + FastMCP 4        │
                    │  /mcp  ·  /api/v1  · /health  │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     adapters/muse.py      contracts.py          jobs.py / monitoring.py
     (Muse tool calls)     (canonical schemas)   (background jobs, monitors)
              │                    │                    │
              └────────────────────┼────────────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │      audit.py (engine)        │
                    │  pick_pages → extract_links   │
                    │  → check_link → verdict →     │
                    │  evidence.build_finding       │
                    └──────┬──────────────┬────────┘
                           ▼              ▼
                    security.py      crawler.py / fetch tiers
                    (SSRF guard)     (Crawlee + requests + Scrapling)
                           │
                           ▼
                    storage.py → Postgres (jsonb) or local JSON
```

## Request flow (audit)

1. **Validate** — `validation.validate_tool_args` enforces the canonical schema
   (`contracts.py`); `security.validate_public_http_url` rejects non-public
   targets before any network I/O.
2. **Discover pages** — `pick_pages()`: WordPress sitemap (scored by
   `intelligence.page_priority`, commercial pages first) → DuckDuckGo
   `site:` fallback → base URL alone.
3. **Extract links** — theme-aware content isolation (strips nav/footer/related;
   Divi `.et_pb_post_content` preferred), absolutize, dedupe, drop internal and
   share-widget links; every URL SSRF-validated.
4. **Check destinations** — `check_link()`: manual redirect walk via
   `security.safe_get` (each hop re-validated), records full chain, final
   status, final URL. 3 retries on transport errors.
5. **Verdict** — `verdict()` applies the honesty rule: only 404/410/5xx or
   soft-404 (deep product URL → homepage/category) become findings. Bot-blocked,
   timeout, connection failure, 403, 503-from-botwall-hosts, and proxy links
   are inconclusive — no finding emitted.
6. **Evidence** — `evidence.build_finding()`: stable ID, severity, confidence,
   revenue-risk score, redirect chain, anchor/heading context, tracking-param
   diff, commerce context, recommendation.

## Fetch tiers

1. `requests` via `safe_get` (default, cheap).
2. On 403 / captcha-looking body / unrendered JS shell → Scrapling
   `DynamicFetcher`/`StealthyFetcher` with headless Chromium.
3. **Invariant:** escalation only ever upgrades a successful fetch. If all
   tiers fail, the original response is returned; upgraded content that is
   itself a captcha page is rejected. The fallback can never create a finding.
   Kill switch: `REVENUE_RESCUE_SCRAPLING=0`.

## Background jobs & monitoring

- `jobs.py`: `ThreadPoolExecutor(max_workers=2)`; `start_audit_job` validates,
  writes `queued` state, runs `_run_job`. Job state persists (Postgres/local
  JSON) so results survive restarts; **in-flight jobs do not resume after a
  crash** (known limitation — orphaned `running` jobs need a reaper).
- `monitoring.py`: monitors hold config + baseline snapshot. `run_monitor`
  re-audits and `diff_snapshots` emits 6 typed change events. Due monitors are
  executed in bounded batches (`limit=5`) by the cron endpoint.
- The cron endpoint (`POST /internal/cron/due-monitors`, separate Bearer
  secret) also prunes audit-job records older than 90 days
  (`storage.prune_states_older_than`).

## State

`storage.py` — tiny key/value API (`put/get/delete/list_state`) over two
whitelisted kinds (`audit_jobs`, `monitors`):

- **Postgres** (`DATABASE_URL`/`SUPABASE_DB_URL`): `revenue_rescue.audit_jobs`,
  `revenue_rescue.monitors` (uuid key, `jsonb` state, `updated_at`).
- **Local fallback:** atomic JSON files under `work/state/<kind>/`.
- Report files: `work/<site>_<ts>/report.json` (working data, not the API).

## What the architecture deliberately avoids

- No dollar-loss estimates (unverifiable; would be fabrication).
- No out-of-stock *findings* (only explicit `schema.org/Discontinued`; OOS is
  context-only — avoids false alarms on transient stock states).
- No per-link time-series DB (baselines replace history; fine-grained tables
  are a documented future step).
- No LLM summarization inside the engine (evidence is deterministic; the agent
  calling the connector does the talking).
