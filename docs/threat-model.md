# Revenue Rescue Threat Model

This document captures the major security boundaries of the public auditing
service and the mitigations currently implemented.

## Assets

- API/connector credentials
- database connection credentials
- audit reports and evidence
- monitor baselines/history
- service availability
- reputation of the service and scanned-site operators

## Trust boundaries

1. Agent/client → Revenue Rescue API/MCP
2. Revenue Rescue → arbitrary public websites
3. Revenue Rescue → Postgres/Supabase
4. Revenue Rescue → scheduler/cron caller
5. Build/deployment pipeline → production runtime

## Threats and mitigations

### SSRF / private network access

**Threat:** A user submits a URL that resolves to localhost, RFC1918/private
space, link-local ranges, cloud metadata, or redirects from a public URL into a
private target.

**Current mitigations:**
- HTTP(S)-only URLs;
- credentials-in-URL rejected;
- local/internal hostnames rejected;
- resolved IPs must be globally routable;
- every redirect destination is revalidated;
- private/link-local/loopback IPs are rejected.

**Residual risk:** DNS rebinding and resolver/network races cannot be eliminated
perfectly by application checks alone.

**Production recommendation:** pair application validation with egress firewall
or network policy that blocks private/metadata destinations.

### Crawl abuse / denial of service

**Threat:** A caller uses Revenue Rescue to generate excessive traffic toward a
target or exhaust Revenue Rescue resources.

**Current mitigations:**
- page limits;
- per-domain bounded crawl work;
- Crawlee concurrency controls;
- bounded due-monitor batches;
- REST rate limiting;
- monitor cadence constraints.

**Residual risk:** REST limiter is currently process-local.

**Production recommendation:** enforce global quotas/rate limits at the gateway
or a shared Redis/Valkey layer before multi-instance scaling.

### Authentication / secret leakage

**Threat:** Unauthorized API or cron access.

**Current mitigations:**
- optional API bearer token;
- independent cron secret;
- constant-time secret comparison;
- no target-site admin credentials required for public audits;
- secrets supplied through environment variables.

**Production recommendation:** rotate secrets, use deployment-platform secret
storage, and move to per-user credentials/OAuth if the connector platform
requires it.

### Data exposure

**Threat:** Audit/monitor evidence is readable by unauthorized users.

**Current mitigations:**
- private Postgres schema;
- no anon/authenticated table grants in the Supabase reference schema;
- reports are served through authenticated application endpoints when auth is
  enabled;
- no browser-side database secret.

**Production recommendation:** finalize retention/deletion policy and add
tenant ownership before supporting multiple untrusted customers.

### False-positive business claims

**Threat:** Revenue Rescue incorrectly labels a site as losing revenue.

**Current mitigations:**
- network timeouts/bot blocks are inconclusive;
- proxy affiliate services are exempt from unverifiable tracking claims;
- explicit evidence and confidence accompany findings;
- deterministic truth-set benchmark tooling;
- precision-first release philosophy.

**Production recommendation:** real-site benchmark before public claims or
directory submission.

### Browser/scraper supply chain

**Threat:** Browser automation and scraping dependencies increase attack
surface.

**Current mitigations:**
- pinned direct dependency versions;
- browser escalation is optional;
- HTTP-first design;
- CI import/regression tests;
- container runs as non-root.

**Production recommendation:** add dependency scanning/SBOM generation and
periodic version review.

## Launch security gates

Before public launch:

- [ ] production API auth enabled
- [ ] cron secret enabled
- [ ] private database configured
- [ ] stable HTTPS endpoint
- [ ] health checks passing
- [ ] private-network egress blocked at infrastructure layer where possible
- [ ] real-site benchmark reviewed
- [ ] retention/deletion policy implemented and published
- [ ] per-customer authorization model defined if multi-tenant accounts launch
- [ ] incident/security contact published
