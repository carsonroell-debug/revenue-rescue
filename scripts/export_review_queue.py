#!/usr/bin/env python3
"""Convert Revenue Rescue reports into a human-labeling review queue.

Input: one or more audit report JSON files.
Output: JSONL rows containing predicted issue types plus compact evidence.
A human reviewer then fills `expected` for benchmark scoring.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def rows_from_report(path: Path) -> list[dict]:
    report = json.loads(path.read_text())
    rows = []

    findings_by_key = {}
    for finding in report.get("findings", []):
        key = (finding.get("page"), finding.get("url"))
        findings_by_key.setdefault(key, []).append(finding)

    for check in report.get("link_checks", []):
        key = (check.get("page"), check.get("url"))
        predicted = sorted({
            f.get("issue_type")
            for f in findings_by_key.get(key, [])
            if f.get("issue_type")
        })
        rows.append({
            "case_id": (
                f"{path.stem}:"
                f"{abs(hash((check.get('page'), check.get('url'))))}"
            ),
            "site": report.get("site"),
            "page": check.get("page"),
            "url": check.get("url"),
            "anchor_text": check.get("anchor_text", ""),
            "is_affiliate": bool(check.get("is_affiliate")),
            "is_cta": bool(check.get("is_cta")),
            "final_status": check.get("final_status"),
            "final_url": check.get("final_url"),
            "redirect_hops": len(check.get("chain", [])),
            "predicted": predicted,
            "expected": [],
            "review_status": "unreviewed",
        })

    for finding in report.get("findings", []):
        if finding.get("issue_type") != "OFFER_DISCONTINUED":
            continue
        rows.append({
            "case_id": f"{path.stem}:{finding.get('finding_id')}",
            "site": report.get("site"),
            "page": finding.get("page"),
            "url": finding.get("url"),
            "anchor_text": "",
            "is_affiliate": False,
            "is_cta": False,
            "final_status": finding.get("evidence", {}).get("final_status"),
            "final_url": finding.get("final_url"),
            "redirect_hops": 0,
            "predicted": ["OFFER_DISCONTINUED"],
            "expected": [],
            "review_status": "unreviewed",
        })

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    all_rows = []
    for report in args.reports:
        all_rows.extend(rows_from_report(report))

    with args.output.open("w") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    print(json.dumps({
        "reports": len(args.reports),
        "cases": len(all_rows),
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
