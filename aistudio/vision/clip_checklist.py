"""V1: vision review of a generated CLIP: build the question, parse the answer.  Standard library only.

Contract (tests in tests/test_clip_checklist.py):
  CHECKLIST: list[str]   exactly these 7 strings, in this order:
     "Only the intended characters appear in every frame (no extra or unknown person)."
     "The face, clothes and background match the first frame."
     "No garbled, random or unwanted on-screen text."
     "No real brand or social-media logos."
     "No broken, ghosted or double-exposed frames, especially in the last second."
     "No distorted faces or hands."
     "If the shot has dialogue, the speaker's mouth is visible in some frames."
  build_prompt(shot: dict, n_frames: int) -> str
      Returns an instruction for a vision model: names the shot id, says there are n_frames frames in time order
      plus the first frame as reference, lists the CHECKLIST numbered 1..7, lists the intended characters from
      shot.get("characters", []) (or "unknown"), and demands ONLY a JSON object of the form
      {"verdict":"pass|warn|fail","findings":[{"frame":int,"issue":str,"severity":"low|medium|high"}],"summary":str}.
  parse_review(text: str) -> dict
      Extracts the first JSON object from `text` (the model may wrap it in prose or ```json fences), validates it:
      verdict in (pass, warn, fail); findings a list of dicts with int frame, non-empty str issue, severity in
      (low, medium, high); summary a str.  Returns the dict.  If nothing parseable/valid was found, returns
      {"verdict":"warn","findings":[],"summary":"could not parse vision review"}.  If any finding has severity
      "high" but verdict is "pass", the verdict is corrected to "fail".  Never raises.
"""
import json
import re

CHECKLIST = [
    "Only the intended characters appear in every frame (no extra or unknown person).",
    "The face, clothes and background match the first frame.",
    "No garbled, random or unwanted on-screen text.",
    "No real brand or social-media logos.",
    "No broken, ghosted or double-exposed frames, especially in the last second.",
    "No distorted faces or hands.",
    "If the shot has dialogue, the speaker's mouth is visible in some frames.",
]

VERDICTS = ("pass", "warn", "fail")
SEVERITIES = ("low", "medium", "high")

_FALLBACK = {"verdict": "warn", "findings": [], "summary": "could not parse vision review"}


def build_prompt(shot, n_frames):
    characters = shot.get("characters") or []
    who = ", ".join(str(c) for c in characters) if characters else "unknown"
    lines = [
        "You are reviewing AI-generated video frames for a shot.",
        "Shot id: %s." % shot.get("id", "unknown"),
        "You get %d frames in time order, plus the first frame as the visual reference." % n_frames,
        "Intended characters: %s." % who,
        "Check every frame against this checklist:",
    ]
    lines += ["%d. %s" % (i + 1, item) for i, item in enumerate(CHECKLIST)]
    lines += [
        "Report only problems you actually see; an empty findings list is fine.",
        'Reply with ONLY a JSON object, no prose and no code fences, of the form '
        '{"verdict":"pass|warn|fail","findings":[{"frame":int,"issue":str,'
        '"severity":"low|medium|high"}],"summary":str}',
    ]
    return "\n".join(lines)


def _valid(obj):
    if not isinstance(obj, dict):
        return False
    if obj.get("verdict") not in VERDICTS:
        return False
    if not isinstance(obj.get("summary"), str):
        return False
    findings = obj.get("findings")
    if not isinstance(findings, list):
        return False
    for f in findings:
        if not isinstance(f, dict):
            return False
        frame, issue, sev = f.get("frame"), f.get("issue"), f.get("severity")
        if isinstance(frame, bool) or not isinstance(frame, int):
            return False
        if not isinstance(issue, str) or not issue.strip():
            return False
        if sev not in SEVERITIES:
            return False
    return True


def _candidates(text):
    try:
        text = str(text)
    except Exception:
        return
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, m.start())
        except ValueError:
            continue
        yield obj


def parse_review(text):
    try:
        for obj in _candidates(text):
            if not _valid(obj):
                continue
            out = {"verdict": obj["verdict"], "findings": obj["findings"], "summary": obj["summary"]}
            if out["verdict"] == "pass" and any(f.get("severity") == "high" for f in out["findings"]):
                out["verdict"] = "fail"
            return out
    except Exception:
        pass
    return dict(_FALLBACK, findings=[])