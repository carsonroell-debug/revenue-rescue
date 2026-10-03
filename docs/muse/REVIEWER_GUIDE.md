# Revenue Rescue — Reviewer Guide

**For:** Meta connector review (end-to-end testing).
Also usable by the developer for pre-submission QA via the Custom Connector
path (Meta doesn't review Custom connectors — ideal for self-testing before
submitting).

## 1. Reach the connector

- MCP endpoint: `https://<host>/mcp` (Streamable HTTP, FastMCP 4)
- REST + OpenAPI: `https://<host>/api/v1/openapi.json`
- Liveness: `GET https://<host>/health` → `{"ok": true, ...}` (public, no auth)
- Readiness: `GET https://<host>/ready` → config + storage health (public)

## 2. Authenticate

If `REVENUE_RESCUE_API_TOKEN` is set (production): `Authorization: Bearer
<token>` on MCP and all `/api/v1` audit/monitor routes. Without the header you
get `401 UNAUTHORIZED`. (Auth is optional in development.)

## 3. Run the 5-minute end-to-end test

```bash
H=https://<host>; T=$REVENUE_RESCUE_API_TOKEN

# 1. Synchronous audit of a small demo site
curl -s -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"site_name":"Demo","base_url":"https://example.com","max_pages":3}' \
  $H/api/v1/audits | head -c 600

# 2. Background audit + poll
AID=$(curl -s -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"site_name":"Demo","base_url":"https://example.com","max_pages":3}' \
  $H/api/v1/jobs | python3 -c "import sys,json;print(json.load(sys.stdin)['audit_id'])")
curl -s -H "Authorization: Bearer $T" $H/api/v1/jobs/$AID

# 3. Findings + explanation
curl -s -H "Authorization: Bearer $T" "$H/api/v1/jobs/$AID/findings"

# 4. Monitor: create, run now, read changes
MID=$(curl -s -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"site_name":"Demo","base_url":"https://example.com","max_pages":3,"cadence_hours":24}' \
  $H/api/v1/monitors | python3 -c "import sys,json;print(json.load(sys.stdin)['monitor_id'])")
curl -s -H "Authorization: Bearer $T" -X POST $H/api/v1/monitors/$MID/run
curl -s -H "Authorization: Bearer $T" $H/api/v1/monitors/$MID/changes
```

Expected: each step returns `{ok: true, ...}` with a `request_id`. The demo
site has few outbound links, so findings may be empty — that is a valid
result (no fabricated findings, ever).

## 4. What "correct" looks like

- A 404 affiliate destination → `BROKEN_DESTINATION` finding with redirect
  chain evidence and a recommendation.
- A bot-blocked/timeout destination → **no finding** (inconclusive by design).
- A Geniuslink/Skimlinks proxy link → **no attribution finding** (server-side
  tagging is unverifiable).
- `GET /api/v1/jobs/<bad-uuid>` → `404 NOT_FOUND` with a retryable=false
  error envelope, never a stack trace.

## 5. Negative tests for reviewers

- `base_url: "http://169.254.169.254/"` → `INVALID_INPUT` / `UnsafeTarget`
  (SSRF blocked).
- No `Authorization` header (when token set) → `401`.
- `max_pages: 500` → clamped/rejected per schema (1–50).

## 6. Notes for the "Anything else?" form field

Suggested text: "Read-only auditing connector. No payments, no writes, no
per-user accounts in V1 (single Bearer token). Reviewer test path above;
demo audits against example.com are safe and side-effect-free. Support:
<support-email-or-URL>."
