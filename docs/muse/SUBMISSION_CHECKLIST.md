# Revenue Rescue — Submission Checklist

**Form:** https://muse.ai/platform (sign-in-gated, 3 steps, 3 attestations).
**Researched:** 2026-10-03 against the Muse Connector Terms (eff. 2026-09-18),
the Connector Policies, and muse.ai/platform.

## BLOCKERS (must resolve before submitting)

- [ ] **Hosting: PUBLIC HTTPS ENDPOINT LIVE.** The connector must be reachable
  from Meta's cloud at submission. IN PROGRESS 2026-10-03: ChatGPT is
  deploying to Vercel; that URL will serve as the product website URL for
  now. Update this line with the live URL when it lands. (Railway ruled out,
  Fly.io blocked by SSO org.) Nothing else below matters until this is
  resolved.
- [x] **Support contact.** `hello@freedomengineers.tech` (default — changeable).
- [x] **Work email for the submitter.** `hello@freedomengineers.tech`
  (default — changeable).
- [ ] **Product website URL.** Form requires it. (freedomengineers.tech or a
  dedicated page — confirm.)
- [x] **Privacy policy + Terms URLs.** Canonical home: the public raw-GitHub
  URLs (already live):
  - Privacy: `https://raw.githubusercontent.com/carsonroell-debug/revenue-rescue/main/docs/privacy.md`
  - Terms: `https://raw.githubusercontent.com/carsonroell-debug/revenue-rescue/main/docs/terms.md`
  (Revisit if a product site ships.)

## Form fields — readiness

| Field | Status |
|---|---|
| Connector name (≤80 chars) | "Revenue Rescue" ✓ |
| Company/developer (≤120 chars) | to confirm |
| Product website (URL) | BLOCKER (see above) |
| Connection type | "Existing MCP" → `https://<host>/mcp` |
| Authentication methods | API keys (Bearer token) — or none for a public read-only listing |
| Example prompts (one per line) | 6 drafted in TOOLS.md ✓ |
| Icon 512×512 PNG/SVG ≤256 KiB | exists: `submission/icon_512.png` — verify dimensions/size |
| Payments | "Does not accept payments" ✓ |
| Submitter name | to confirm |
| Work email | `hello@freedomengineers.tech` (default — changeable) |
| Support email/URL | `hello@freedomengineers.tech` (default — changeable) |
| Privacy policy URL | `https://raw.githubusercontent.com/carsonroell-debug/revenue-rescue/main/docs/privacy.md` ✓ |
| Terms of service URL | `https://raw.githubusercontent.com/carsonroell-debug/revenue-rescue/main/docs/terms.md` ✓ |
| "Anything else?" | reviewer text drafted in REVIEWER_GUIDE.md ✓ |

## Pre-submit QA (from TEST_PLAN.md)

- [ ] Endpoint live; `/health`, `/ready`, `/api/v1/openapi.json` public.
- [ ] All 10 MCP tools exercised end-to-end (Reviewer Guide script).
- [ ] Auth + SSRF negative tests pass.
- [ ] Trialed as a Muse Custom Connector first (unreviewed path — catches
  integration issues before Meta's e2e test).
- [ ] `scripts/release_check.py` passes on the release commit.
- [ ] Listing claims match behavior exactly (Terms §4.1: the connector "must
  perform as described in your submission materials" — claims are binding).

## Attestations (step 3, all required)

1. Authorized to submit the connector and brand assets.
2. Submission doesn't guarantee approval; featuring is editorial/usage-based.
3. Agreement to the Muse Connector Terms.

## After submitting

- No published review SLA — budget for an indeterminate wait.
- Do not advertise the listing before approval (form guidance).
- 1,500+ applications in launch week: approval is competitive, not automatic.
- Keep the endpoint up and the support contact monitored; Meta may re-review
  at any time.
