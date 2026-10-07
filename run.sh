#!/bin/sh
# Revenue Rescue - local run script (zero spend, everything local)
# Port comes from the PORT env var (default 8787) via RuntimeConfig; server.py
# takes no CLI flags.
cd "$(dirname "$0")" || exit 1
exec ./venv/bin/python -m revenuerescue.server
