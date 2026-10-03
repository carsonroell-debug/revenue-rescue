# Changelog

All notable changes to Revenue Rescue should be documented here.

The project follows semantic versioning for public releases.

## [Unreleased] - audit/p0-20261003 (senior-audit pass, NOT merged to main)

### Why this branch exists
Post-merge audit of main @ 722dc53 (8 ChatGPT-agent PRs). Verified the Oct-1
P1s against the real code, fixed the highest-confidence gaps with minimal
changes, and wrote the /docs/muse/ submission package from the actual
implementation. Nothing here is merged; CI runs on push.

### Fixed
- **503 bot-wall false positive (verdict):** `verdict()` had a dead
  `body_sniff` captcha guard — no caller ever passed a body, so a 503 from a
  bot-wall host was reported as "destination server error (503)", contradicting
  the "bot-blocked is never a finding" invariant. 503s from known bot-wall
  hosts (BOTWALL list) are now inconclusive; genuine 503s elsewhere still
  report. (`revenuerescue/audit.py`, +2 tests)
- **Scrapling upgrade could launder a bot-wall into a clean 200:**
  `_maybe_upgrade_fetch` now rejects upgraded content that is itself a
  captcha/challenge page and keeps the original response, preserving the
  "escalation only upgrades fetch success" invariant. (`revenuerescue/audit.py`,
  +2 tests)
- **Contract drift:** the `health_check` MCP tool was registered in
  `server.py` but missing from the canonical `contracts.py` (adapters'
  parity test couldn't see it). Added to TOOLS.

### Added
- **Retention enforcement (P2-7):** `storage.prune_states_older_than(kind,
  max_age_days=90)` — deletes audit-job records older than 90 days on both
  backends (Postgres `updated_at`, local JSON mtime). Refuses non-`audit_jobs`
  kinds (monitor configs are user-owned and never auto-pruned). Wired into
  `POST /internal/cron/due-monitors` so it actually runs. (+3 tests)
- **/docs/muse/** submission package: CONNECTOR.md, TOOLS.md, ARCHITECTURE.md,
  SECURITY.md, PRIVACY.md, DATA_FLOW.md, REVIEWER_GUIDE.md, TEST_PLAN.md,
  SUBMISSION_CHECKLIST.md — all written from the real implementation.

### Fixed (tests)
- `test_run_audit_persists_structured_report` did a live DNS lookup for
  example.com (fails under DNS-intercepting sandboxes). Now stubs
  `validate_public_http_url`. Test suite: 48/48 passing.

### What remains (for the next coding agent)
- P0: public HTTPS hosting (decision parked by user) — the #1 submission
  blocker; Meta requires the endpoint live at submission.
- P0: support contact, work email, product website URL, canonical
  privacy/terms home (see docs/muse/SUBMISSION_CHECKLIST.md).
- P1: robots.txt enforcement (Meta Policies prohibit violating robots.txt;
  crawler currently doesn't check it).
- P1: crash recovery for in-flight background jobs (orphaned
  `running`/`queued` jobs after restart need a reaper).
- P1: per-user auth story (V1 is a single static Bearer token; fine for
  single-operator, needs OAuth/API-key issuance for multi-tenant listing).
- P2: truth-set labeling pass (benchmarks/sample.jsonl has 3 rows;
  benchmark gates can't run meaningfully yet).
- P2: dead code cleanup (`commerce.commerce_weight()` uncalled, stale
  `__version__` in `revenuerescue/__init__.py`, `run.sh --port` silently
  ignored).
- P2: fine-grained Postgres tables (architecture doc lists audit_pages,
  link_checks, findings, monitor_runs — only the two jsonb tables exist).

## [0.4.0] - 2026-10-02

### Added
- FastMCP-based MCP transport and REST/OpenAPI service.
- Background audit jobs.
- SSRF-safe URL validation and redirect handling.
- Evidence-first findings with stable IDs, confidence, severity, and Revenue Risk Score.
- Crawlee orchestration with Scrapling escalation.
- Product/Offer JSON-LD extraction.
- Persistent website monitors and deterministic change events.
- Postgres/Supabase-ready durable state.
- Structured logging, request IDs, rate limits, and secure cron execution.
- Truth-set benchmark tooling and review-queue exporter.
- Commercial-page prioritization.
- Direct affiliate tracking-drop detection.
- Explicit discontinued-offer findings.
- Cross-platform canonical connector contracts.
- Input validation at agent/API boundaries.
- Non-root production container and health/readiness probes.
- Security policy and threat model.
- Release preflight checks, container verification workflow, and dependency automation.

### Changed
- Revenue Rescue evolved from a one-shot affiliate link scanner into an
  agent-native commerce observability service.
- API surface now favors durable background jobs and monitor resources over
  legacy local report-file endpoints.
- Privacy/terms drafts now match the actual pre-launch data flows and avoid
  unenforced retention/commercial promises.

### Removed
- Legacy adapter-only audit listing/report file API behavior.
