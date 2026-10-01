#!/bin/sh
# One command to run AI Studio locally (macOS / Linux). Same thing as: python3 scripts/start.py
cd "$(dirname "$0")/.."
exec python3 scripts/start.py
