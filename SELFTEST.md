# Revenue Rescue - Self-Test in Your Own Muse (via custom connectors)

Goal: wire the locally-running Revenue Rescue server into YOUR Muse account
as a custom connector (private to you, no Meta review) and run a first real
audit. Takes about 15 minutes. Nothing is submitted anywhere in this process.

## What you need
- This project folder on a machine that stays on during the test
- A way to expose your laptop to the internet (step 2)

## Step 1 - Start the server
Open a terminal on your laptop:

    cd ~/workspace/goals/start-a-remote-business/connector
    ./run.sh

You should see: "Revenue Rescue listening on http://127.0.0.1:8787".
Leave that terminal running. In a second terminal, sanity-check it:

    curl localhost:8787/health
    # expect: {"ok": true, "service": "revenue-rescue"}

## Step 2 - Expose it with a free tunnel (no signup)
Install cloudflared once (free, no account):

    # macOS:  brew install cloudflared
    # Linux:  download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

Then run:

    cloudflared tunnel --url http://localhost:8787

Copy the https://...trycloudflare.com URL it prints. Example:
https://quiet-donkey-42.trycloudflare.com

Keep this running. Your server is now reachable at:
- MCP endpoint:  https://quiet-donkey-42.trycloudflare.com/mcp
- API docs:      https://quiet-donkey-42.trycloudflare.com/api/v1/openapi.json

(Tunnel URLs change each restart; that is fine for a self-test.)

## Step 3 - Add it as a custom connector in Muse
In Muse (app or web), go to Settings > Connectors, or just ask Muse:

    "Connect a custom service for me. It is an MCP server at
    https://quiet-donkey-42.trycloudflare.com/mcp
    with API docs at
    https://quiet-donkey-42.trycloudflare.com/api/v1/openapi.json.
    It audits publisher websites for revenue leaks."

Muse will walk you through saving it. No API key is needed for the self-test.

Note: custom connectors are private to your account and are not reviewed by
Meta. This is the documented power-user path, separate from the public
directory submission.

## Step 4 - Run your first audit
Ask Muse:

    "Use Revenue Rescue to audit majorhifi.com for revenue leaks."

What should happen:
1. Muse calls the audit_site tool with the site name and URL.
2. The server discovers review pages, extracts outbound links, and checks
   each destination (takes 2-5 minutes for 8 pages).
3. Muse reports back a ranked list of confirmed findings.

## Step 5 - Verify the results make sense
- Findings should be specific: a URL, the page it was found on, and the
  problem (e.g. "404 at destination", "missing affiliate tracking parameter").
- Pages that timed out or blocked the scanner must NOT appear as findings;
  they are inconclusive by design. If you see bot-blocked URLs reported as
  broken, that is a bug - tell Raptor.
- Skimlinks/Geniuslink proxy links should never be flagged for missing tags.

## Step 6 (optional) - Test the REST path directly
    curl -X POST https://quiet-donkey-42.trycloudflare.com/api/v1/audits \
      -H 'Content-Type: application/json' \
      -d '{"site_name":"MajorHiFi","base_url":"https://www.majorhifi.com","max_pages":2}'

## Troubleshooting
- "Connection refused" in Muse: the tunnel URL changed or cloudflared stopped.
  Restart step 2 and update the connector URL.
- Audit finds 0 pages: the site's sitemap may be blocking; the server falls
  back to web-search-discovered review URLs automatically.
- Slow: each link check waits politely between requests; 8 pages takes a few
  minutes. Reduce max_pages for quicker tests.

## When the self-test passes
The connector is ready for the submission package in submission/. Nothing is
submitted without your explicit approval.
