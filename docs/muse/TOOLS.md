# Revenue Rescue — Tool Reference

**Source of truth:** `revenuerescue/contracts.py` (canonical schemas),
`revenuerescue/server.py` (`_build_mcp`, REST handlers),
`revenuerescue/adapters/muse.py`. All 10 tools below are live on both MCP
(`/mcp`) and REST (`/api/v1`).

Conventions: every response is `{ok: true, ...}` or `{ok: false, error: {...}}`
with machine-readable error codes (`INVALID_INPUT`, `UNAUTHORIZED`,
`NOT_FOUND`, `RATE_LIMITED`, `NOT_READY`, `INTERNAL_ERROR`) and a `retryable`
flag. Every REST response carries `X-Request-ID`.

---

## 1. `audit_site` — synchronous small audit

Runs a full audit inline and returns the report. For quick checks (≤ ~10 pages).
Long scans should use `start_audit` + polling instead.

| arg | type | required | notes |
|---|---|---|---|
| `site_name` | string | yes | human label |
| `base_url` | string (http/https) | yes | SSRF-validated; public hosts only |
| `max_pages` | integer 1–50 | no | default 8 |

Returns: `{ok, summary (plain text), findings[], stats, report_path}`.
REST: `POST /api/v1/audits` (rate limit 30/min per IP).

## 2. `start_audit` — background audit

Queues a background audit job and returns `audit_id` immediately. For larger
sites or when the caller doesn't want to wait.

| arg | type | required | notes |
|---|---|---|---|
| `site_name` | string | yes | |
| `base_url` | string (http/https) | yes | SSRF-validated |
| `max_pages` | integer 1–50 | no | default 8 |

Returns: `{ok, audit_id, status: "queued"}`. REST: `POST /api/v1/jobs`.

## 3. `get_audit_status`

| arg | type | required |
|---|---|---|
| `audit_id` | string (uuid) | yes |

Returns: `{ok, audit_id, status: queued|running|completed|failed, stats}`.
REST: `GET /api/v1/jobs/{audit_id}`.

## 4. `get_findings`

| arg | type | required | notes |
|---|---|---|---|
| `audit_id` | string (uuid) | yes | |
| `severity` | enum: info|low|medium|high|critical | no | filter |
| `issue_type` | string | no | filter, e.g. `BROKEN_DESTINATION` |

Returns findings with stable IDs (`rr_<sha256>`), severity, confidence
(0.80–0.99), revenue-risk score (0–100), evidence (redirect chain, anchor text,
tracking params, commerce context), and a per-finding recommendation.
REST: `GET /api/v1/jobs/{audit_id}/findings`.

Issue types: `BROKEN_DESTINATION`, `DESTINATION_SERVER_ERROR`,
`PRODUCT_DESTINATION_GONE`, `REDIRECT_CHAIN`, `AFFILIATE_TRACKING_DROPPED`,
`AFFILIATE_TRACKING_MISSING`, `OFFER_DISCONTINUED`, `DESTINATION_CHANGED`.

**Honesty rule (core invariant):** a finding is only "confirmed" when a plain
re-fetch proves the destination dead (404/410/5xx or soft-404). Bot-blocked,
timeout, or connection-failed is **never** a finding — it is reported as
inconclusive (no finding emitted). Proxy links (Geniuslink/Skimlinks) are
unverifiable server-side and never produce attribution findings.

## 5. `explain_finding`

| arg | type | required |
|---|---|---|
| `audit_id` | string (uuid) | yes |
| `finding_id` | string | yes |

Returns the finding plus a plain-language explanation and recommended action.
REST: `GET /api/v1/jobs/{audit_id}/findings/{finding_id}`.

## 6. `monitor_site` — persistent change monitoring

Creates a recurring monitor. The first run establishes a baseline; later runs
diff against it and emit typed change events.

| arg | type | required | notes |
|---|---|---|---|
| `site_name` | string | yes | |
| `base_url` | string (http/https) | yes | SSRF-validated |
| `max_pages` | integer 1–50 | no | default 8 |
| `cadence_hours` | integer 1–720 | no | default 24 |

Returns: `{ok, monitor_id}`. REST: `POST /api/v1/monitors`.

## 7. `run_monitor_now`

| arg | type | required |
|---|---|---|
| `monitor_id` | string (uuid) | yes |

Runs a full audit now, diffs against the baseline, stores new baseline.
REST: `POST /api/v1/monitors/{monitor_id}/run`.

## 8. `get_monitor_status`

| arg | type | required |
|---|---|---|
| `monitor_id` | string (uuid) | yes |

Returns monitor config + latest-run metadata (not the full baseline).
REST: `GET /api/v1/monitors/{monitor_id}`.

## 9. `get_monitor_changes`

| arg | type | required |
|---|---|---|
| `monitor_id` | string (uuid) | yes |

Returns the latest deterministic change events, severity-ordered
(critical → info). Event types: `DESTINATION_CHANGED`,
`DESTINATION_STATUS_CHANGED`, `TRACKING_DROPPED`, `NEW_REVENUE_RISK`,
`REVENUE_RISK_RESOLVED`, `OFFER_DATA_CHANGED`.
REST: `GET /api/v1/monitors/{monitor_id}/changes`.

## 10. `health_check`

No arguments. Returns `{ok: true, service: "revenue-rescue", mcp: "fastmcp-4"}`.

---

## Example prompts (for the submission form)

- "Check my site for confirmed revenue risks"
- "Start an audit of my website and tell me when it finishes"
- "Explain the highest-risk finding"
- "Monitor this site daily and tell me what changes"
- "Did any of my affiliate links break since last week?"
- "Which of my product links lost their tracking parameters?"
