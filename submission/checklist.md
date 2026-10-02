# Revenue Rescue — Connector Readiness Checklist

Status: **prepared, not submitted**.

This checklist intentionally separates product readiness from platform-specific
submission details. Platform requirements can change; verify the current
official connector/developer documentation immediately before submission.

## Product readiness

- [x] Connector/product name: Revenue Rescue
- [x] MCP endpoint implementation
- [x] REST + OpenAPI implementation
- [x] Canonical tool contracts shared across adapters
- [x] Background audits
- [x] Evidence-backed findings
- [x] Stable finding IDs + explanations
- [x] Persistent monitoring + change detection
- [x] SSRF protections
- [x] Optional bearer authentication
- [x] Rate limiting
- [x] Structured logs/request IDs
- [x] Durable Postgres/Supabase-ready persistence
- [x] Cron-safe due-monitor execution
- [x] CI/regression suite
- [x] Benchmark/truth-set tooling
- [ ] Public production endpoint deployed
- [ ] Production database attached
- [ ] Production API + cron secrets configured
- [ ] 20–30 site benchmark completed
- [ ] Precision target met on reviewed truth set
- [ ] End-to-end connector dogfood completed

## Listing assets

- [x] Draft listing copy: `submission/listing_copy.md`
- [x] Example prompts: `submission/example_prompts.md`
- [x] Draft privacy policy: `submission/privacy_policy.md`
- [x] Draft terms: `submission/terms_of_service.md`
- [x] 512px icon asset
- [ ] Confirm final product website URL
- [ ] Publish privacy policy at stable public product URL
- [ ] Publish terms at stable public product URL
- [ ] Confirm support contact
- [ ] Verify current platform-required fields/auth requirements
- [ ] Verify current submission/review process from official documentation

## Technical endpoints to verify after deployment

- `/mcp`
- `/api/v1/openapi.json`
- `/api/v1/jobs`
- `/api/v1/jobs/{audit_id}`
- `/api/v1/jobs/{audit_id}/findings`
- `/api/v1/jobs/{audit_id}/findings/{finding_id}`
- `/api/v1/monitors`
- `/api/v1/monitors/{monitor_id}`
- `/api/v1/monitors/{monitor_id}/run`
- `/api/v1/monitors/{monitor_id}/changes`
- `/health`

## Submission gate

Do not submit merely because the endpoint is technically reachable.

Submit when all of these are true:

1. hosted endpoint is stable;
2. auth and rate limits are configured;
3. privacy/terms URLs are stable;
4. real-site benchmark precision is strong;
5. natural-language agent testing reliably selects the correct Revenue Rescue
   tool;
6. monitor/create/run/change workflows work end to end;
7. current platform submission requirements have been re-verified.
