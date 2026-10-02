# Revenue Rescue

**Agent-native commerce observability for websites.**

Revenue Rescue audits public websites for confirmed revenue risks, produces
evidence-first findings, and monitors those risks over time. Muse is the first
target connector, but the backend is platform-neutral and exposes both MCP and
REST/OpenAPI.

> Product principle: prove the web failure first; let the agent explain it.
> Revenue Rescue does not invent lost-revenue dollar estimates.

## What Revenue Rescue detects

Current deterministic signals include:

- broken destinations (404/410)
- destination server errors
- product soft-404s / redirects to home or category pages
- unhealthy redirect chains
- missing affiliate tracking
- affiliate tracking parameters disappearing
- CTA-linked failures
- destination changes over time
- destination status changes over time
- new and resolved revenue-risk findings
- structured Product/Offer changes from JSON-LD

Bot blocks, timeouts, and transient connection failures are **inconclusive**,
not confirmed revenue leaks.

## Agent tool surface

The MCP service exposes a deliberately small set of tools:

- `audit_site` — small synchronous audit
- `start_audit` — start a background audit
- `get_audit_status` — poll background audit state
- `get_findings` — retrieve/filter completed findings
- `explain_finding` — explain one stable finding ID with evidence
- `monitor_site` — create a persistent monitor
- `run_monitor_now` — run a monitor immediately
- `get_monitor_status` — inspect monitor state
- `get_monitor_changes` — retrieve latest deterministic change events
- `health_check`

## Architecture

```text
Muse / ChatGPT / Claude / MCP clients
                 |
              FastMCP 4
                 |
         Revenue Rescue
        /       |        \
 background   evidence   monitoring
   audits      engine      engine
      |           |           |
   Crawlee ---- safe fetch ----|
      |           |
 HTTP-first    Scrapling escalation
                 |
          private Postgres
           (Supabase-ready)
```

### Crawl layer

- Crawlee coordinates bounded concurrency, retry, and request scheduling.
- Revenue Rescue validates every target as public HTTP(S) before fetching.
- Redirects are followed manually through the SSRF guardrail.
- Scrapling may improve fetch success for JS/bot-protected pages.
- Scrapling never turns an inconclusive response into a confirmed finding.

### Evidence layer

Each finding has:

- stable `finding_id`
- issue type
- severity
- confidence
- Revenue Risk Score (0–100)
- source page
- destination URL/final URL
- redirect evidence
- CTA/anchor/heading context
- structured commerce context
- tracking-parameter evidence
- recommended action

The score ranks commercial importance. It is **not** an estimate of dollars
lost.

### Monitoring layer

Monitors create an evidence baseline and later emit machine-readable events:

- `DESTINATION_CHANGED`
- `DESTINATION_STATUS_CHANGED`
- `TRACKING_DROPPED`
- `NEW_REVENUE_RISK`
- `REVENUE_RISK_RESOLVED`
- `OFFER_DATA_CHANGED`

The first monitor run only creates a baseline.

## Interfaces

When running locally:

- MCP Streamable HTTP: `http://127.0.0.1:8787/mcp`
- REST audits: `http://127.0.0.1:8787/api/v1/audits`
- OpenAPI: `http://127.0.0.1:8787/api/v1/openapi.json`
- Health: `http://127.0.0.1:8787/health`
- Internal cron: `POST /internal/cron/due-monitors`

## Production environment

Optional/required runtime variables:

| Variable | Purpose |
| --- | --- |
| `REVENUE_RESCUE_API_TOKEN` | Bearer protection for MCP and protected REST operations |
| `REVENUE_RESCUE_CRON_SECRET` | Separate bearer secret for the internal due-monitor cron endpoint |
| `DATABASE_URL` | Private Postgres connection string |
| `SUPABASE_DB_URL` | Alternative Postgres connection env name |
| `REVENUE_RESCUE_SCRAPLING` | Set `0` to disable Scrapling escalation |
| `SCRAPLING_CHROME_PATH` | Explicit Chromium path when needed |
| `PORT` | HTTP port; defaults to 8787 |

Do not expose Postgres/service-role credentials to a browser client.

## Persistence

Without a database connection, development state is stored under
`work/state/`.

With `DATABASE_URL` / `SUPABASE_DB_URL`, audit jobs and monitors use a
private `revenue_rescue` Postgres schema.

See `docs/postgres_schema.sql` for the schema reference. When attaching a
real Supabase project, create the actual migration through the Supabase CLI
workflow rather than treating the reference SQL file as migration history.

## Scheduled monitoring

A scheduler (Fly cron, Supabase Cron/Edge Function, GitHub Actions, or another
trusted scheduler) can call:

```http
POST /internal/cron/due-monitors
Authorization: Bearer <REVENUE_RESCUE_CRON_SECRET>
```

Each tick runs a **bounded** batch of due monitors. The scheduler endpoint is
separate from the normal API token.

## Security

Current controls include:

- SSRF protection for initial URLs and redirect hops
- blocks private, loopback, link-local, metadata-style and local hostnames
- no non-HTTP(S) crawl targets
- optional bearer auth
- separate cron secret
- REST rate limiting
- request IDs and structured JSON logs
- bounded monitor execution
- confirmed-only finding policy
- internal Postgres schema with no anon/authenticated table access

Production egress/network policy should still be used as defense in depth.

## Benchmarks

Revenue Rescue includes a labeled truth-set harness:

```bash
python scripts/benchmark.py benchmarks/sample.jsonl
```

For a release gate:

```bash
python scripts/benchmark.py benchmarks/truth-set.jsonl \
  --min-precision 0.95 \
  --min-recall 0.85
```

**Primary quality metric: precision.** A false claim that a site is losing
revenue is worse than staying silent on an uncertain fetch.

See `benchmarks/README.md`.

## Development

```bash
python -m pip install -r requirements.txt
REVENUE_RESCUE_SCRAPLING=0 python -m unittest discover -s tests -v
python -m revenuerescue.server
```

CLI audit:

```bash
python -m revenuerescue.audit "Example" https://example.com 8
```

## Repository layout

```text
revenuerescue/
  audit.py        scanning/verdict pipeline
  crawler.py      Crawlee orchestration
  commerce.py     Product/Offer structured-data extraction
  evidence.py     finding IDs, classification, evidence, risk score
  security.py     SSRF-safe HTTP validation/fetching
  jobs.py         background audit jobs
  monitoring.py   snapshots, diffs, monitor execution
  storage.py      local/Postgres state abstraction
  ops.py          structured logs and edge rate limiting
  server.py       FastMCP + REST/OpenAPI + cron surface
  adapters/       platform-specific contracts

benchmarks/       truth-set documentation/data
scripts/          benchmark tooling
submission/       Muse submission assets
docs/             architecture and persistence references
tests/            regression suite
```

## Current production sequence

The implementation is intentionally split into reviewable stacked PRs:

1. production foundation
2. Crawler 2.0 + commerce evidence
3. monitoring/change detection
4. durable Postgres persistence
5. production operations + benchmark gates

Before a public launch:

1. merge the stack in order
2. attach private Postgres/Supabase
3. configure API + cron secrets
4. deploy publicly
5. run a 20–30 site labeled benchmark
6. fix false positives until precision is strong
7. dogfood through Muse custom connector
8. finalize connector listing/privacy/terms
9. submit for directory review when the interaction is reliable

## Connector status

The repository contains prepared Muse submission assets, but code readiness and
directory submission are separate milestones. Do not submit until the hosted
endpoint, privacy/terms URLs, benchmark quality, and connector behavior have
been verified end-to-end.
