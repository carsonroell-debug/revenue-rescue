# Revenue Rescue - Submission Checklist (PREPARED, NOT SUBMITTED)

Submission route (verified live 2026-10-01): https://muse.ai/platform
Flow: 1) Describe your product -> 2) Submit for review -> 3) Appear in the
directory. Review covers functional, security, and legal requirements plus
end-to-end testing. No public SLA; 1,500+ applications were already in the
queue as of Meta Connect (Sept 23, 2026).

STATUS: Nothing has been submitted. Cars must approve before anything is sent.

## Per the submission form (community-documented fields), current readiness:

- [x] Connector name: "Revenue Rescue"
- [x] Product website: linkrescue.io (placeholder - confirm the live URL before submitting)
- [x] Example prompts: submission/example_prompts.md (6 prompts)
- [x] Icon 512x512: submission/icon_512.png
- [x] Privacy policy: submission/privacy_policy.md - public URL: https://raw.githubusercontent.com/carsonroell-debug/revenue-rescue/main/docs/privacy.md
- [x] Terms of service: submission/terms_of_service.md - public URL: https://raw.githubusercontent.com/carsonroell-debug/revenue-rescue/main/docs/terms.md
- [x] Support contact: hello@freedomengineers.tech
- [x] Company (work) email: hello@freedomengineers.tech
- [ ] Hosted MCP endpoint URL: NOT READY - the server currently runs locally.
      Needs public hosting (free tier) before the "Existing MCP" path can be used.
- [ ] API URL + docs URL: the OpenAPI spec exists at /api/v1/openapi.json, but
      also needs a public base URL for the "Raw API" path.
- [x] Access requirements: documented in listing_copy.md
- [x] Auth methods: none required (documented); per-user API key planned for volume use
- [x] Accepts payments toggle: No (connector itself is free)

## Blocked on Cars:
1. Approve the listing copy, prompts, privacy policy, and terms as written.
2. Confirm the product website URL (linkrescue.io?).
3. Hosting: PARKED per his 2026-10-01 decision - revisit when the other gates are
   decided. Fly.io deploy was prepped (Dockerfile, fly.toml pushed) but blocked:
   his Fly account can't create API tokens (org SSO requirement). Fallback is a
   Vercel rework (async audits) - his call.
4. ~~Publish privacy policy + terms at public URLs.~~ DONE 2026-10-01 (raw GitHub URLs above; GitHub Pages pending account provisioning).

## Code
Public repo: https://github.com/carsonroell-debug/revenue-rescue (personal account;
transfer to carsonlabs org later if wanted).

## Known unknowns (from platform research, unchanged):
- OpenAPI/MCP protocol version requirements, review timelines/SLA, approval
  criteria detail, developer security/PII rules, monetization/fee terms,
  connector ranking logic, "Muse Connector Terms" legal text.
