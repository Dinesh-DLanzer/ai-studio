"""Vision analysis of uploaded character images.
Determines whether an uploaded image is a full character master sheet
(containing multi-angle body views and facial expression/reaction grid)
or merely a single-angle / face reference photo.
"""
import json
import re
from pathlib import Path

PROMPT_CHARACTER_ANALYSIS = """You are an expert character concept artist and vision quality evaluator.
Analyze this uploaded image of a character.

In professional video generation pipelines, a true CHARACTER MASTER SHEET (character model sheet) MUST have:
1. Multiple body angles (e.g. front view, side/profile view, back view, 3/4 turnarounds).
2. Multiple facial expressions / reactions in a grid (e.g. neutral, happy, angry, sad, surprised, laughing, thinking, etc.).
3. Optional close-up details (face close-up, outfit/accessories).

If the image is just a single portrait, a single photo of a person walking/standing, a face selfie, or a photo without turnaround angles and without an expression grid, it is NOT a full character sheet; it is a "character reference only" (or face reference).

Evaluate the image and respond with ONLY a JSON object:
{
  "is_character_sheet": true or false,
  "kind": "full_character_sheet" or "character_ref_only",
  "has_multiple_angles": true or false,
  "has_facial_expressions": true or false,
  "angles_detected": ["front", "side", "back", ...],
  "expressions_detected": ["neutral", "happy", ...],
  "character_description": "short description of character's appearance, clothes, age, gender",
  "summary": "Clear 1-sentence explanation of why it is or is not a full character sheet",
  "suggested_prompt": "Prompt to generate a complete character sheet based on this reference (e.g. 'Character reference sheet of <Name/Description>: full-body front, side, and back views, plus a grid of facial expressions labelled NEUTRAL, HAPPY, ANGRY, SAD, SURPRISED, THINKING, LAUGHING, plus close-ups of face and clothing detail.')"
}
"""

_FALLBACK_ANALYSIS = {
    "is_character_sheet": False,
    "kind": "character_ref_only",
    "has_multiple_angles": False,
    "has_facial_expressions": False,
    "angles_detected": [],
    "expressions_detected": [],
    "character_description": "",
    "summary": "Image appears to be a single photo/reference rather than a multi-angle character sheet.",
    "suggested_prompt": "Character reference sheet: full-body front, side and back views, plus a grid of facial expressions labelled NEUTRAL, HAPPY, ANGRY, SAD, SURPRISED, THINKING, LAUGHING, CONCERNED, plus close-ups of the face and clothing detail."
}


def build_character_check_prompt():
    return PROMPT_CHARACTER_ANALYSIS


def parse_character_analysis(text):
    """Parse JSON response from the vision model."""
    try:
        text = str(text)
        for m in re.finditer(r"\{", text):
            try:
                obj, _ = json.JSONDecoder().raw_decode(text, m.start())
                if isinstance(obj, dict) and "is_character_sheet" in obj:
                    is_sheet = bool(obj.get("is_character_sheet"))
                    has_angles = bool(obj.get("has_multiple_angles"))
                    has_expr = bool(obj.get("has_facial_expressions"))
                    # Both angles and expressions are required for a true character model sheet
                    if not (has_angles and has_expr):
                        is_sheet = False
                    return {
                        "is_character_sheet": is_sheet,
                        "kind": "full_character_sheet" if is_sheet else "character_ref_only",
                        "has_multiple_angles": has_angles,
                        "has_facial_expressions": has_expr,
                        "angles_detected": list(obj.get("angles_detected") or []),
                        "expressions_detected": list(obj.get("expressions_detected") or []),
                        "character_description": str(obj.get("character_description") or "").strip(),
                        "summary": str(obj.get("summary") or "").strip(),
                        "suggested_prompt": str(obj.get("suggested_prompt") or "").strip() or _FALLBACK_ANALYSIS["suggested_prompt"],
                    }
            except ValueError:
                continue
    except Exception:
        pass
    return dict(_FALLBACK_ANALYSIS)


DRIFT_THRESHOLD = 0.6      # identity score below this is flagged by verification


def build_drift_prompt(characters):
    names = ", ".join(characters)
    return (f"You are checking identity consistency. The first images are reference images of these characters, in order: {names}. "
            "The LAST image (or frames) is a generated result. For each character that appears in the result, score from 0.0 to 1.0 how well "
            "the face, hair, skin tone, age and outfit match that character's reference (1.0 = clearly the same person). "
            'Respond with ONLY a JSON object: {"scores": {"<character id>": <0.0-1.0>}, "summary": "one sentence"}. '
            "Leave out a character that does not appear in the result.")


def parse_drift(text, characters):
    """-> {"scores": {id: float}, "summary": str}. Unparseable output gives empty scores (never a made-up score, so nothing is flagged)."""
    try:
        for m in re.finditer(r"\{", str(text)):
            try:
                obj, _ = json.JSONDecoder().raw_decode(str(text), m.start())
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("scores"), dict):
                scores = {}
                for k, v in obj["scores"].items():
                    if k in characters and isinstance(v, (int, float)) and not isinstance(v, bool):
                        scores[k] = round(min(1.0, max(0.0, float(v))), 3)
                return {"scores": scores, "summary": str(obj.get("summary") or "").strip()}
    except Exception:
        pass
    return {"scores": {}, "summary": "The vision model did not return identity scores."}


def drift_findings(pdir, shot_ids, threshold=DRIFT_THRESHOLD):
    """Verification findings for every shot whose stored check (checks/<id>.json) has a character below the threshold. Free: reads files."""
    out = []
    for sid in shot_ids:
        f = Path(pdir) / "checks" / f"{sid}.json"
        try:
            scores = (json.loads(f.read_text(encoding="utf-8")) or {}).get("scores") or {}
        except (OSError, ValueError, AttributeError):
            continue
        low = {k: v for k, v in scores.items() if isinstance(v, (int, float)) and v < threshold}
        if low:
            out.append({"where": sid, "severity": "medium", "issue": "identity drift: " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(low.items())) + f" (below {threshold})",
                        "fix": "Regenerate the shot with the character's identity views as references, or pick another variant."})
    return out
