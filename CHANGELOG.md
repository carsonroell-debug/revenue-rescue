# Changelog

All notable changes to Revenue Rescue should be documented here.

The project follows semantic versioning for public releases.

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
