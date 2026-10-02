# Revenue Rescue Deployment Runbook

This runbook covers the production release path after the stacked PRs are
merged and the real-site benchmark gate is satisfied.

## 1. Pre-release gates

Before deploying a production release:

- CI is green on the release commit.
- Container workflow is green.
- Truth-set benchmark meets the agreed precision/recall gates.
- Privacy/terms accurately describe the production configuration.
- Security contact is published.
- Database migration/reference schema has been applied to the target database.
- Production secrets are available in the deployment platform.

Run:

```bash
python scripts/release_check.py
```

## 2. Required production configuration

Set:

- `REVENUE_RESCUE_ENV=production`
- `REVENUE_RESCUE_API_TOKEN=<strong secret>`
- `REVENUE_RESCUE_CRON_SECRET=<different strong secret>`
- `DATABASE_URL=<private Postgres/Supabase connection>`
- `PORT=8787` unless the platform injects another port

Optional:

- `REVENUE_RESCUE_SCRAPLING=0` to disable browser escalation
- `SCRAPLING_CHROME_PATH=...` only if automatic Playwright discovery is not sufficient

Never expose database credentials or service secrets to browser code.

## 3. Database

Use a private Postgres/Supabase schema as described in
`docs/postgres_schema.sql`.

After applying the schema, verify the application connection can:

- `select 1`;
- read/write `revenue_rescue.audit_jobs`;
- read/write `revenue_rescue.monitors`.

## 4. Deploy

Build from the exact release commit/tag.

The container must run as the non-root `appuser`.

After deployment, check:

```text
GET /health  -> 200
GET /ready   -> 200
GET /api/v1/openapi.json -> 200
```

`/health` means the process is alive.

`/ready` means production configuration and state storage are usable.

Do not route connector traffic to an instance returning 503 from `/ready`.

## 5. Smoke test

Using a low-risk test site you control or have permission to audit:

1. start a background audit;
2. poll the job until completion;
3. fetch findings;
4. explain a finding if one exists;
5. create a monitor;
6. run it once to establish a baseline;
7. fetch monitor status and changes.

Do not use the first production smoke test for broad third-party crawling.

## 6. Scheduler

Configure a trusted scheduler to call:

```http
POST /internal/cron/due-monitors
Authorization: Bearer <REVENUE_RESCUE_CRON_SECRET>
```

Use a cadence appropriate to the monitor product. The server caps each tick to
a bounded number of monitor runs.

## 7. Connector dogfood

Before directory submission:

- connect the hosted MCP endpoint to the intended agent client;
- verify tool discovery;
- test audit start/status/findings/explanation;
- test monitor creation/run/changes;
- confirm the agent correctly treats inconclusive network failures as
  inconclusive;
- record any tool-selection failures as product bugs.

## 8. Rollback

If a release introduces bad findings, auth failures, persistence issues, or
crawler instability:

1. stop new connector traffic if needed;
2. roll back to the previous known-good image/tag;
3. keep the database intact unless a migration itself is defective;
4. disable scheduled monitor execution if monitoring is the source of load;
5. document the regression and add a test/truth-set case before redeploying.

## 9. Post-release checks

Watch:

- readiness failures;
- 429 rate-limit volume;
- scan/job failures;
- monitor failures;
- crawl latency;
- inconclusive fetch rate;
- findings by issue type;
- false-positive reports;
- Postgres availability.

The quality metric that matters most remains **precision**.
