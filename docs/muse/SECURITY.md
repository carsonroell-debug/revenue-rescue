# Revenue Rescue — Security

**Implementation:** `revenuerescue/security.py`, `config.py`, `ops.py`,
`revenuerescue/server.py` (auth), `docs/threat-model.md`, `SECURITY.md`.

## Threat model summary

The connector fetches **user-supplied URLs** (the site the user asks to audit)
and follows their outbound links. The primary risks are SSRF (a crafted URL or
a malicious redirect bouncing the crawler into internal infrastructure),
credential leakage, and abuse (using the scanner as a free proxy/crawler).

## SSRF protection (`security.py`)

- Scheme allowlist: `http`/`https` only.
- URLs containing credentials (`user:pass@host`) rejected.
- Hostname blocklist: `localhost`, `metadata.google.internal`, `metadata`,
  `*.local`, `*.internal`, `*.localhost`.
- **DNS-resolution check:** hostnames (and IP literals) must resolve
  *exclusively* to globally routable addresses. Non-public IPs rejected.
- **Every redirect hop re-validated:** `safe_get` follows redirects manually
  (`allow_redirects=False`, max 8 hops) and runs `validate_public_http_url` on
  each `Location` target, so a public URL cannot bounce the crawler into
  RFC1918/link-local/metadata addresses.
- Applied at: audit base URL, page fetch, every outbound link check, sitemap
  fetch, DuckDuckGo fallback discovery.

**Residual risks (documented, not hidden):**

- DNS-rebinding TOCTOU between validation and request. Mitigation recommended
  for production: egress firewall / network policy (defense in depth; the
  module docstring says this explicitly).
- No `robots.txt` enforcement yet — the crawler fetches pages the user
  explicitly asks it to audit, but it does not currently check robots.txt.
  Tracked as a P1 follow-up.

## Authentication & authorization

- MCP + REST: static Bearer token (`REVENUE_RESCUE_API_TOKEN`), enforced via
  FastMCP `StaticTokenVerifier` and constant-time comparison on REST.
- Cron endpoint: separate Bearer secret (`REVENUE_RESCUE_CRON_SECRET`).
- **Production refuses to boot** without token + cron secret + database URL
  (`assert_startup_ready` raises `RuntimeError`).
- `/health`, `/ready`, `/api/v1/openapi.json` are intentionally public
  (liveness/readiness/discovery only — no user data).
- **V1 limitation:** single static token, no per-user tenants, no OAuth.
  Suitable for a single-operator connector; per-user auth is the planned
  upgrade if the listing needs multi-tenancy.

## Rate limiting (`ops.py`)

In-memory sliding window per client IP: 30/min for audit creation, 60/min
elsewhere. Exceeding returns `RATE_LIMITED` with `Retry-After: 60`.
Documented as Redis-replaceable for multi-instance deployments.

## Input validation (`validation.py`, `contracts.py`)

All tool arguments validated against canonical JSON schemas before execution:
required fields, `additionalProperties: false`, integer ranges, string enums,
`format: uri` (http/https). Malformed MCP/REST input returns `INVALID_INPUT`,
never an exception trace.

## Secrets handling

- Secrets come from environment variables only; never in code, logs, or tool
  outputs. `config.public_status()` exposes booleans (configured/not), never
  values.
- Structured logs (`ops.log_event`) carry request IDs and event names only.

## Crawl politeness

- Concurrency bounded (Crawlee: desired 2, max 4; `max_tasks_per_minute=90`).
- Per-link politeness delay (0.15–0.35s) in the serial path.
- `max_pages` clamped to 1–50 per audit; monitor cron batches capped at 5.
- Browser escalation (Scrapling/Chromium) only triggers on bot-walls or
  JS-shells — it is not used for bulk fetching.

## Incident response

- Security contact: **to be supplied** (see Submission checklist).
- Commitment: notify Meta within 48 hours of any security incident involving
  user data, per the Connector Terms §4.3(b).
- Responsible-disclosure policy: `docs/threat-model.md` (deployment-hardening).

## Dependencies & supply chain

Pinned in `requirements.txt` (8 direct deps). Dependabot enabled for GitHub
Actions and pip. Container CI builds the Docker image and verifies non-root
runtime (`appuser`, uid 10001).
