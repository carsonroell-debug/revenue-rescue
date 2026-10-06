# Revenue Rescue benchmark

The scanner should improve from labeled evidence, not vibes.

Create a JSONL truth set with one row per evaluation case:

```json
{"case_id":"publisher-a-link-1","expected":["BROKEN_DESTINATION"],"predicted":["BROKEN_DESTINATION"]}
{"case_id":"publisher-a-link-2","expected":[],"predicted":["REDIRECT_CHAIN"]}
{"case_id":"publisher-b-link-1","expected":["AFFILIATE_TRACKING_MISSING"],"predicted":[]}
```

Run:

```bash
python scripts/benchmark.py benchmarks/sample.jsonl
```

Optional release gates:

```bash
python scripts/benchmark.py benchmarks/sample.jsonl --min-precision 0.95 --min-recall 0.85
```

## Labeling rules

- Label only issues a human can verify from evidence.
- Bot blocks/timeouts are `inconclusive`, not broken links.
- Do not label speculative dollar losses.
- Keep false positives visible; do not delete hard cases.
- Add regression cases whenever a user reports a wrong finding.

Primary production metric: **precision**. Revenue Rescue should prefer silence over falsely claiming a business is losing money.
