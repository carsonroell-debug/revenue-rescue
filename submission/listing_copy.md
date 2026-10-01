# Revenue Rescue - Connector Directory Listing Copy (DRAFT, not submitted)

Connector name: Revenue Rescue
Tagline: Find the places your website is losing revenue.
Category: Business / Website tools
Support contact: hello@freedomengineers.tech

## Short description (for directory card)
Revenue Rescue audits any publisher website for revenue leaks: dead affiliate
links, missing tracking tags, and product pages that quietly redirect to
nowhere. Ask Muse to check a site and get a plain-English report of confirmed
leaks, ranked by severity.

## Long description
Affiliate publishers lose money silently every day: a product goes out of
stock and the link 404s, a tracking tag drops off a URL, a merchant page
redirects to a homepage that earns nothing. Revenue Rescue finds these leaks
automatically.

Give it a site URL and it:
- Discovers the site's review and roundup pages (via sitemap, with web-search
  fallback)
- Extracts outbound affiliate and merchant links using theme-aware content
  parsing (handles WordPress, Divi, and custom themes)
- Re-checks every destination with a plain HTTP fetch and reports only
  confirmed findings: 404/410s, server errors, soft-404 redirects, long
  redirect chains, and missing affiliate tracking parameters
- Never reports a leak it cannot confirm: bot-blocked pages, timeouts, and
  connection failures are marked inconclusive, not broken

Built for independent publishers, content sites, and SEO agencies that manage
affiliate revenue across many pages.

## Access requirements
No account required for audits. The connector only fetches public pages of
websites the user explicitly names. Rate limits apply to bulk automated use.

## Auth method
None required (public audit API). A per-user API key option is available for
high-volume use.

## Accepts payments
No. The connector itself is free to use; human-led recovery services are
offered separately outside the connector.
