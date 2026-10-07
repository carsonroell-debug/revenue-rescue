# Revenue Rescue — Test Plan

## Unit tests (CI)

- Runner: `python -m unittest discover -s tests` (CI also runs with
  `REVENUE_RESCUE_SCRAPLING=0` so browser tiers stay out of unit tests).
- Current: **48 tests, all passing** (branch `audit/p0-20261003`).
- CI additionally: `compileall`, production ASGI import check
  (`from revenuerescue.server import app, MCP`), `scripts/release_check.py`
  preflight (version/files/tools/OpenAPI/contracts), container build +
  non-root verification.

## Coverage by area

| Area | What's tested |
|---|---|
| Verdict honesty | 404/410 → finding; timeout/botwall/403/503-from-botwall/proxy → inconclusive; soft-404 (deep→homepage, product→category); tracking-param drop; Amazon missing tag |
| SSRF | loopback, private ranges, metadata hosts, credential URLs, per-hop redirect validation |
| Fetch upgrade | captcha-content upgrade rejected; clean upgrade adopted |
| Evidence | stable finding IDs, tracking diff, CTA boost, severity/confidence/score |
| Intelligence | page prioritization, discontinued-vs-OOS distinction |
| Commerce | JSON-LD product/offer extraction |
| Monitoring | snapshot diffs (tracking drop, new/resolved risks, offer change), due-monitor cadence |
| Storage | local round-trip, delete, retention pruning (old deleted, new kept, monitors refused) |
| Jobs | start/status/findings contract, error envelope on missing job |
| Validation | schema enforcement, bad-URI rejection, unknown tool rejection |
| Contracts | adapter parity (Muse/OpenAI/server tool names), OpenAPI operationIds |
| Release | semver format, error-envelope shape |
| Pipeline | `run_audit` persists a structured report |

## Deliberate gaps (not covered, by design or as known follow-ups)

- No live-network end-to-end tests (would be flaky; reviewer guide covers
  manual e2e against the deployed endpoint).
- Scrapling browser tiers: env-gated off in CI; covered by the upgrade
  unit tests with fakes.
- Truth-set benchmark: `scripts/benchmark.py` + `benchmarks/sample.jsonl`
  (3 rows) exist, but there is no meaningful labeled dataset yet — precision/
  recall gates can't run meaningfully until a human labeling pass happens.
- Crash recovery for in-flight jobs: no reaper yet (documented limitation).

## Pre-submission QA checklist (run against the deployed endpoint)

1. `/health` and `/ready` answer from the public internet.
2. All 10 MCP tools exercised via the Reviewer Guide script.
3. Auth negative tests: no token → 401; bad token → 401.
4. SSRF negative tests: `169.254.169.254`, `localhost` → rejected.
5. One real-world audit of a consenting affiliate site; spot-check 2–3
   findings by hand (the benchmark harness scores this when labeled data
   exists).
6. Cron endpoint with the cron secret: due monitors run; old audit jobs pruned.
7. `scripts/release_check.py` passes on the release commit.
