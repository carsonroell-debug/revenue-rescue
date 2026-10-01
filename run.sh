#!/bin/sh
# Revenue Rescue - local run script (zero spend, everything local)
cd "$(dirname "$0")" || exit 1
exec ./venv/bin/python -m revenuerescue.server --port 8787
