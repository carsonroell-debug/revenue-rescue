# Revenue Rescue — Data Flow

## One audit, end to end

```
Muse ──tool call──▶ /mcp ──▶ adapter ──▶ validate args + SSRF-check URL
                                              │
                                              ▼
                                   pick_pages (sitemap → search → base)
                                              │
                                              ▼
                                   fetch pages (requests → Scrapling if walled)
                                              │  (HTML held in memory only)
                                              ▼
                                   extract outbound links + context
                                              │
                                              ▼
                              check_link per URL: redirect walk, final status
                                              │
                                              ▼
                                   verdict → evidence.build_finding
                                              │
                              ┌───────────────┴───────────────┐
                              ▼                               ▼
                    report.json (work/ dir)        job state (Postgres/local)
                    findings[] + stats                     │
                              └───────────────┬───────────────┘
                                              ▼
                              Muse ◀── tool response (findings + evidence)
```

## What crosses the boundary back to Muse

Only the tool response: finding summaries, evidence (redirect chains, anchor
text, tracking-param diffs), stats, and plain-language explanations. Raw page
HTML is never returned. Full report JSON stays connector-side (referenced by
`report_path` / `audit_id`).

## What is stored, where, for how long

| Store | Contents | Lifetime |
|---|---|---|
| Postgres `revenue_rescue.audit_jobs` (or `work/state/audit_jobs/*.json`) | job status, stats, full findings array | pruned after 90 days by cron |
| Postgres `revenue_rescue.monitors` (or `work/state/monitors/*.json`) | monitor config, baseline snapshot, last-20-run history | until user deletes the monitor |
| `work/<site>_<ts>/report.json` | full working report | working data; superseded by state |
| stdout JSONL logs | request IDs, event names, counts | operational; no user content |

## Third parties

The connector makes outbound HTTPS requests **only** to:

1. the user-supplied audit target and the outbound link destinations found on
   its pages (for verification);
2. `html.duckduckgo.com` — only as a fallback page-discovery signal when the
   target's sitemap is unreachable (no user data sent; query is
   `site:<target-host> review`).

No analytics, no trackers, no data brokers. Dependencies are libraries, not
services.
