"""Vision analysis of uploaded character images.
Determines whether an uploaded image is a full character master sheet
(containing multi-angle body views and facial expression/reaction grid)
or merely a single-angle / face reference photo.
"""
import json
import re

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
