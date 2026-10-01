"""Is a project a TEST project (nothing real was ever generated) or an actual one?  Standard library only.

Evidence, from the files themselves (never from the app's current mode):
  * real:  a cost-log row (images, clips, reviews; not chat text) for a model that is not "fake/...", or a clip file that is not the test-mode placeholder;
  * test:  every cost-log row is for a "fake/..." model, or every clip is the placeholder (b"FAKEMP4...").
A project marked with sandbox.json (the 'Test pipeline' switch) is a test project unless it holds real evidence.
A project with no media and no costs yet is an ordinary project (nothing to say it is a test).
"""
import csv
from pathlib import Path

PLACEHOLDER = b"FAKEMP4"


def evidence(pdir):
    """(real, test): booleans from the cost log and the clips."""
    pdir = Path(pdir)
    real = test = False
    rows = []
    f = pdir / "cost_log.csv"
    if f.is_file():
        try:
            with open(f, newline="", encoding="utf-8") as fh:
                rows = [r for r in csv.DictReader(fh) if (r.get("model") or "").strip() and r.get("shot") != "_ai"]   # "_ai" = chat / verify text calls: a test pipeline uses a real chat AI
        except (OSError, UnicodeDecodeError, csv.Error):
            rows = []
    if rows:
        fakes = [r["model"].startswith("fake/") for r in rows]
        real = real or not all(fakes)
        test = test or all(fakes)
    clips = [c for c in (pdir / "clips").glob("*.mp4") if c.is_file()] if (pdir / "clips").is_dir() else []
    if clips:
        marks = []
        for c in clips:
            try:
                with open(c, "rb") as fh:
                    marks.append(fh.read(len(PLACEHOLDER)) == PLACEHOLDER)
            except OSError:
                marks.append(False)
        real = real or not all(marks)
        test = test or all(marks)
    return real, test


def is_test_project(pdir):
    real, test = evidence(pdir)
    if real:
        return False
    return (Path(pdir) / "sandbox.json").exists() or test
