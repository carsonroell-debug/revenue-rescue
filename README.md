# Revenue Rescue - Connector for the LinkRescue Business

"Revenue Rescue" is the connector-brand name for LinkRescue's audit engine:
ask any AI agent to check a publisher website for places it is losing revenue,
and get back a ranked report of confirmed leaks (dead affiliate links, missing
tracking tags, soft-404 product redirects).

## What it does
- Discovers a site's review/roundup pages (sitemap, with web-search fallback)
- Extracts outbound affiliate/merchant links with theme-aware parsing
  (WordPress, Divi, custom themes - boilerplate stripped first)
- Re-verifies every destination with a plain HTTP fetch and reports ONLY
  confirmed findings. Bot-blocked pages, timeouts, and connection failures are
  inconclusive, never findings. Geniuslink/Skimlinks proxy links are never
  flagged for missing tags (they attach the tag server-side).

## Layout
    connector/
      README.md            this file
      SELFTEST.md          step-by-step: wire it into your own Muse, run a first audit
      run.sh               starts the local server
      venv/                local Python env (requests, beautifulsoup4, mcp, pillow)
      revenuerescue/
        audit.py           the audit engine (hardened from linkscan.py)
        server.py          one process: REST API + MCP streamable-HTTP endpoint
        adapters/
          __init__.py      AgentAdapter: THE ABSTRACTION BOUNDARY (see below)
          muse.py          Muse tool contract (audit_site, list_audits)
          openai.py        ChatGPT app-extension shaped contract (same engine)
      submission/          PREPARED ONLY - NOTHING SUBMITTED
        privacy_policy.md  terms_of_service.md  listing_copy.md
        example_prompts.md  icon_512.png  checklist.md
      work/                audit reports (JSON) - scanner intermediates live here,
                           never in /tmp

## Run locally
    cd ~/workspace/goals/start-a-remote-business/connector
    ./run.sh
    # REST:  http://127.0.0.1:8787/api/v1/audits
    # MCP:   POST http://127.0.0.1:8787/mcp   (streamable HTTP, JSON-RPC 2.0)
    # Docs:  http://127.0.0.1:8787/api/v1/openapi.json

CLI audit (no server):
    ./venv/bin/python -m revenuerescue.audit "Site Name" https://example.com 8

## The abstraction boundary
`revenuerescue/audit.py` knows nothing about agents: it takes
(site_name, base_url) and returns a report dict. Every platform-specific
concern (tool names, JSON schemas, invocation conventions, response shaping)
lives in `revenuerescue/adapters/` behind the `AgentAdapter` interface
(describe() + invoke()).

- `adapters/muse.py` defines the canonical tool contract used by BOTH the MCP
  endpoint and the REST API, so the submission works down either of Meta's two
  ingestion paths ("Existing MCP" or "Raw API + OpenAPI").
- `adapters/openai.py` proves the engine is portable: same audit, ChatGPT
  app-extension function shape. A future Claude/Gemini port = one new adapter
  file, zero engine changes.

## 7-day plan mapping
1. Working backend ......... DONE: revenuerescue/audit.py (tested end-to-end)
2. Working MCP/API ......... DONE: server.py (MCP streamable-HTTP + REST + OpenAPI)
3. Self-test via custom connector ... READY: SELFTEST.md (needs Cars to run it)
4. Official submission ...... PREPARED ONLY: submission/ package; blocked on
   Cars's approval + public hosting for the endpoint (Railway excluded per his
   instruction) + public URLs for the policy/terms.

## Scanner caveats (from operational notes, applied verbatim in audit.py)
1. Geniuslink/Skimlinks-style proxy links' "missing tag" verdicts are false
   positives -> treated as unverified, not findings, unless the destination
   itself is dead.
2. Bot-blocked / timeout / connection-failed is NOT a broken link -> only
   findings a plain re-fetch confirms dead (404/410/5xx/soft-404) are reported.
3. is_affiliate() covers creator shorteners incl. lvnta.com (Levanta, tag=maas).
4. Theme-aware content extraction (Divi-safe); first-<article> matching removed.
5. pick_pages() falls back to web-search-discovered review URLs on slow sitemaps.
6. Intermediates stay in work/, never /tmp.

## Status / blockers
- Backend + MCP + REST + OpenAPI: built and smoke-tested locally 2026-10-01
  (real audit of majorhifi.com: 1 page, 14 links, 0 findings, report in work/).
- Submission route verified live 2026-10-01: https://muse.ai/platform
  (describe -> submit for review -> directory). The actual submit form needs a
  signed-in session; nothing was or will be submitted without Cars's approval.
- Blocked: public hosting decision (free tier, not Railway), policy/terms public
  URLs, Cars's approval of copy, and Cars running SELFTEST.md.
