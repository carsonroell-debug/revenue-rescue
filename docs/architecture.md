# Production Architecture

Revenue Rescue should stay an **agent-native analysis engine**, not become a
dashboard-heavy SaaS. Muse is the first distribution channel; MCP and REST are
the stable product boundary.

## Target stack

### Agent/API edge
- **FastMCP 4** for MCP Streamable HTTP, protocol negotiation, auth support,
  middleware, and future MCP background-task support.
- **Starlette/Uvicorn** for the small REST/OpenAPI surface and health endpoints.
- Keep platform adapters thin. The scanner must not know whether Muse, ChatGPT,
  Claude, or a direct API caller requested the work.

### Crawl engine
Adopt **Crawlee for Python** as the crawl coordinator in the next phase:
- request queue and deduplication
- bounded concurrency / autoscaling
- retries and session management
- HTTP-first crawling with Playwright escalation for JS-heavy pages
- per-domain crawl limits

Keep **Scrapling** as a specialized escalation layer for pages where normal
HTTP or browser fetches are blocked. It should improve fetch coverage only;
it must never turn an inconclusive request into a "confirmed revenue leak."

Do not make a hosted scraping API (Firecrawl, Browserbase, etc.) a hard
dependency for the core product. Optional providers can be added later.

### Evidence engine
A finding must be evidence-first and deterministic where possible:
1. source page + anchor/CTA context
2. original destination URL
3. redirect chain
4. final status + final URL
5. affiliate/tracking evidence
6. issue type and confidence
7. machine-readable remediation hint

AI may summarize evidence, but it should not invent the finding itself.

### Durable state
Move production state from local JSON files to Postgres/Supabase:
- audits
- audit_pages
- link_checks
- findings
- monitors
- monitor_runs
- api_keys / usage

Keep JSON export as a convenience format only.

### Long-running work
Do not keep production crawls tied to one HTTP request.
Near-term options:
1. MCP background tasks via FastMCP where the client supports them.
2. Explicit `start_audit` / `get_audit` tools for universal compatibility.

Use Redis/Valkey-backed task execution when horizontal scaling is required.

### Observability and safety
- structured logs with request/audit IDs
- per-domain concurrency caps and global rate limits
- SSRF protection: block loopback, RFC1918/private, link-local and metadata IPs
- robots/site policy handling documented explicitly
- maximum response/body sizes
- bearer/OAuth authentication for public tool calls
- no credentials required for read-only public-site audits
- metrics for crawl success, inconclusive fetches, false-positive corrections,
  p50/p95 latency and findings by type

## Product tool surface

Keep the agent surface narrow:

- `start_audit(domain, max_pages, modes?)`
- `get_audit(audit_id)`
- `get_findings(audit_id, severity?, type?)`
- `explain_finding(finding_id)`
- `monitor_site(domain, cadence)`
- `get_changes(monitor_id)`

The current synchronous `audit_site` tool remains useful for tiny scans and
local testing, but should not be the only production path.

## Upgrade order

1. Standards-based MCP/ASGI foundation + tests/CI.
2. SSRF/rate-limit/input hardening.
3. Crawlee coordinator with existing verdict logic preserved.
4. Postgres/Supabase persistence + asynchronous audit jobs.
5. Monitoring/diff engine.
6. Richer revenue signals: CTA context, stale offers, destination changes,
   attribution loss, discontinued products and commerce-health modules.
