# Revenue Rescue — Privacy

**Public policy:** `docs/privacy.md` (raw-GitHub URL for the submission form;
canonical home: the product website, TBD).
**Terms:** `docs/terms.md`.

## What data the connector handles

| Data | Source | Purpose |
|---|---|---|
| Site name + base URL supplied by the user | Muse tool call | the audit target |
| Public page HTML of the audited site | fetched by the connector | link extraction |
| Outbound link URLs, anchor text, headings | extracted from the above | findings |
| Redirect chains, final URLs, HTTP statuses | fetched by the connector | destination verification |
| Public product/offer JSON-LD | extracted from page HTML | commerce context |
| Audit reports, monitor configs, baselines | generated | delivering results / change detection |

## What it does NOT collect

- No account credentials, no payment data, no personal data beyond what is
  publicly visible on the audited site's pages.
- No browsing history, no data from other connectors, no Meta-side
  conversation content beyond the tool arguments Muse passes.

## Data minimization

- Only the pages needed for the audit are fetched (`max_pages`, default 8,
  hard cap 50). Internal links are dropped; only outbound links are checked.
- Tool arguments are the only user data exchanged; the connector never pulls
  more than the requested scan requires.

## Retention & deletion

- **Audit reports:** retained only as long as needed to deliver results and
  support follow-up questions. The cron endpoint prunes audit-job records
  older than **90 days** (`storage.DEFAULT_RETENTION_DAYS`,
  `prune_states_older_than`). Monitor configurations (user-owned recurring
  watches) are never pruned automatically.
- **On revocation / deletion request:** disconnecting the connector stops all
  further data exchange. Stored audit reports and monitor configs for the
  tenant are deleted via `storage.delete_state`; Postgres rows are hard-deleted
  (`delete from ... where id = ...`), local JSON files are unlinked.
- **No sale, no sharing:** user data is processed only to fulfill the scan the
  user requested and is never sold, rented, or disclosed to another recipient.

## Controller relationship

Per the Muse Connector Terms, the developer and Meta act as **independent
controllers**. This notice describes the developer's processing; Meta's
processing is described by Meta's own policies.

## User rights

Users may request access to, correction of, or deletion of their stored audit
data via the support contact (see Submission checklist). Deletion requests are
honored by removing the corresponding state records as described above.
