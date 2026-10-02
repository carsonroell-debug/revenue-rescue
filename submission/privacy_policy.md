# Revenue Rescue — Privacy Policy (Draft)

**Status:** pre-launch draft. Final public retention periods, hosting providers,
and business contact details must be confirmed before publication.

## 1. What Revenue Rescue does

Revenue Rescue audits public websites for evidence-backed commerce and
monetization risks and can monitor those sites over time for meaningful
changes.

Examples include broken merchant destinations, affiliate attribution loss,
soft-404 product redirects, explicitly discontinued offers, and destination
changes.

## 2. Data Revenue Rescue processes

Depending on the feature used, the service may process and store:

- the public website URL and site name submitted by the user;
- public pages and outbound URLs needed to perform an audit;
- HTTP status and redirect evidence;
- link/CTA context such as anchor text and nearby headings;
- public Product/Offer structured data;
- generated findings, risk scores, and recommended actions;
- monitor configuration and prior evidence snapshots used for comparison;
- technical service logs such as request IDs, timestamps, status, and errors.

## 3. Data Revenue Rescue does not need for public-site audits

Revenue Rescue does not require the scanned website's:

- administrator password;
- CMS credentials;
- private customer database;
- payment card data;
- private pages or intranet URLs.

Production access to Revenue Rescue itself may use an API or connector
credential. That credential authenticates access to Revenue Rescue; it is not a
credential for the website being scanned.

## 4. How data is used

Processed data is used to:

- perform requested audits;
- create and operate requested monitors;
- compare current evidence with prior baselines;
- return findings and explanations to the requesting client/agent;
- secure, debug, and improve service reliability.

Revenue Rescue does not sell audit or monitor data to advertisers.

## 5. Public website requests

Revenue Rescue makes automated requests to public HTTP(S) pages needed to
perform the requested audit or monitor run. Rate limits and crawl bounds are
used to limit load.

Private/local network targets are blocked by application-level SSRF controls.

## 6. Storage and retention

Audit jobs and monitor state may be stored on access-controlled server
infrastructure so background work and recurring monitoring can function across
deployments.

**Before public launch, the final production retention schedule and deletion
process must be finalized and published here.** The deployed service should not
claim a retention period that is not technically enforced.

## 7. Service providers

Production infrastructure providers may process data on Revenue Rescue's behalf
for hosting, database, logging, or delivery. The final published policy should
name or categorize the providers actually used in production.

## 8. Security

Current technical safeguards include HTTPS at the deployment edge, authenticated
API access when configured, request rate limits, SSRF protections, bounded
monitor execution, structured request IDs, and access-controlled database
storage.

No internet service can guarantee absolute security.

## 9. User requests

Before public launch, Revenue Rescue will publish a stable support contact for
privacy, access, correction, and deletion requests.

## 10. Changes

The public policy should display its effective date and be updated when material
data practices change.
