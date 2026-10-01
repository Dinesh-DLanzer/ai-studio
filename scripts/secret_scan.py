#!/usr/bin/env python3
"""Fail if a tracked file looks like it contains an API key. Used by CI and before any public release."""
import re, subprocess, sys
PATTERNS = [r"sk-or-[A-Za-z0-9_-]{20,}", r"sk-[A-Za-z0-9]{32,}", r"AIza[0-9A-Za-z_-]{35}", r"OPENROUTER_API_KEY\s*=\s*[^\s#\"'+]{12,}"]
files = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split("\n")
bad = []
for f in files:
    if not f or f.endswith((".png", ".jpg", ".mp4", ".lock")) or f == "scripts/secret_scan.py":
        continue
    try:
        text = open(f, encoding="utf-8", errors="ignore").read()
    except OSError:
        continue
    for p in PATTERNS:
        for m in re.finditer(p, text):
            if not re.search(r"your|xxx|example|placeholder|changeme", m.group(0), re.I):
                bad.append((f, p))
if bad:
    print("POSSIBLE SECRETS:", *bad, sep="\n  "); sys.exit(1)
print("secret scan: clean (%d tracked files)" % len([f for f in files if f]))
