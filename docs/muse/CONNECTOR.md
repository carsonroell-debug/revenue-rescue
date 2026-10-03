# Revenue Rescue — Connector Overview

**For:** Meta Muse Connector Platform submission (muse.ai/platform)
**Prepared:** 2026-10-03 · Branch: `audit/p0-20261003` (not merged)
**Source of truth:** the implementation in `revenuerescue/`, not this document.

## What it is

Revenue Rescue audits a website for **confirmed revenue risks**: broken affiliate
links, dead product destinations, redirect chains that lose attribution, and
affiliate tracking parameters dropped in transit. It then **monitors** the site
and reports deterministic before/after changes (destination changed, tracking
dropped, new/resolved risks, offer data changed).

Target user: an independent publisher or content-site owner who monetizes with
affiliate links and wants to know — with evidence, not guesses — where money is
leaking.

## Connection type

**Existing MCP** (primary) — Streamable HTTP at `/mcp`, served by FastMCP 4.
A **Raw API** (REST + generated OpenAPI 3.0.3 at `/api/v1/openapi.json`) exposes
the same canonical tool contracts and is the fallback track.

The connector is **developer-hosted** at a public HTTPS endpoint. Meta does not
host connectors. The endpoint must be live and reachable from Meta's cloud at
submission time (hosting decision is currently PARKED — see Submission blockers).

## Read-only by design

Every tool **reads and reports**. Nothing in the connector:

- moves money, places orders, or touches payments;
- publishes, sends, or edits anything on the user's behalf;
- deletes user data (except the connector's own retention pruning of old audit
  reports, and explicit per-report delete via storage API);
- makes autonomous professional determinations (no legal/financial/medical advice).

This puts it in the lowest-risk tier for review: retrieve-only, no
high-consequence actions.

## Authentication

- **MCP + REST:** optional static Bearer token (`REVENUE_RESCUE_API_TOKEN`).
  When set, all audit/monitor endpoints require it (constant-time compare);
  `/health`, `/ready`, and `/api/v1/openapi.json` stay public.
- **Cron:** separate Bearer secret (`REVENUE_RESCUE_CRON_SECRET`) for the
  internal due-monitors endpoint.
- **Production refuses to boot** without token + cron secret + database
  (`config.assert_startup_ready`). In development, auth is optional.
- **No OAuth / no per-user accounts in V1.** One token = one tenant. This is
  documented as a known limitation (see P0 blockers).

## Payments

**Does not accept payments.** There is no checkout, no Stripe flow, and no
transaction Muse could complete inside the connector. (The separate $499
Recovery Sprint is a human-led service sold off-platform; it is not part of
this connector.)

## Support

- Support contact: required for submission — **to be supplied** (support email
  or URL goes in the form; not yet chosen).
- Public status: `GET /health` (liveness), `GET /ready` (readiness + config
  and storage health).

## Versioning

Semantic versioning (`revenuerescue/version.py`, currently `0.4.0`).
`docs/versioning.md` defines the release policy. `scripts/release_check.py`
runs a preflight (version/files/tools/OpenAPI/contracts) in CI.
