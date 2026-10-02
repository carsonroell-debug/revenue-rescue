#!/usr/bin/env python3
"""Evaluate Revenue Rescue findings against a hand-labeled truth set.

Truth-set JSONL format:
{"case_id":"site-1","expected":["BROKEN_DESTINATION"],"predicted":["BROKEN_DESTINATION"]}
{"case_id":"site-2","expected":[],"predicted":["REDIRECT_CHAIN"]}

Use one row per audited case/page/link grouping. This deliberately evaluates
issue classification, not dollar-loss estimates.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def score(rows: list[dict]) -> dict:
    tp = fp = fn = 0
    by_type: dict[str, Counter] = {}

    for row in rows:
        expected = set(row.get("expected", []))
        predicted = set(row.get("predicted", []))
        tp_set = expected & predicted
        fp_set = predicted - expected
        fn_set = expected - predicted
        tp += len(tp_set)
        fp += len(fp_set)
        fn += len(fn_set)

        for issue in expected | predicted:
            bucket = by_type.setdefault(issue, Counter())
            if issue in tp_set:
                bucket["tp"] += 1
            elif issue in fp_set:
                bucket["fp"] += 1
            elif issue in fn_set:
                bucket["fn"] += 1

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    per_type = {}
    for issue, counts in sorted(by_type.items()):
        p = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 1.0
        r = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 1.0
        per_type[issue] = {
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
            "precision": round(p, 4),
            "recall": round(r, 4),
        }

    return {
        "cases": len(rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate_over_predictions": round(fp / (tp + fp), 4) if tp + fp else 0.0,
        "per_issue_type": per_type,
    }


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if "expected" not in row or "predicted" not in row:
            raise ValueError(f"{path}:{line_number}: expected and predicted are required")
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("truth_set", type=Path)
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    args = parser.parse_args()

    result = score(load_jsonl(args.truth_set))
    print(json.dumps(result, indent=2))

    if args.min_precision is not None and result["precision"] < args.min_precision:
        raise SystemExit(2)
    if args.min_recall is not None and result["recall"] < args.min_recall:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
