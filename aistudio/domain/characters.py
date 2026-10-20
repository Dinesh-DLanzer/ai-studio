"""Character domain: character image prompt building, reference linking, and vision analysis."""
from pathlib import Path

from aistudio import character_check
from aistudio.domain.common import ServiceError


class CharacterDomain:
    def __init__(self, ws):
        self.ws = ws

    def _image_spec(self, p, img_id):
        imgs = self.ws._read(p, "images.json", {"images": []})
        by = {i["id"]: i for i in imgs["images"]}
        if img_id not in by:
            raise ServiceError(f"unknown image id {img_id}")
        spec = by[img_id]
        refs = []
        spec_refs = list(spec.get("refs", []))
        # If character has no explicit refs, check if any uploaded reference exists matching character id
        if spec.get("kind") == "character" and not spec_refs:
            for i in imgs.get("images", []):
                if i.get("kind") == "other":
                    iid = i["id"].lower()
                    if iid == img_id.lower() or iid.startswith(f"{img_id.lower()}_") or img_id.lower() in iid:
                        spec_refs.append(i["id"])
        for r in spec_refs:
            path = p / by[r]["out"] if r in by else p / r
            if not path.exists():
                raise ServiceError(f"reference not found: {r}")
            refs.append(path)
        base_prompt = (imgs.get("style", "") + " " + spec["prompt"]).strip()
        if spec.get("kind") == "character":
            # Guarantee multi-angle body views and facial expression grid
            p_lower = base_prompt.lower()
            if not any(k in p_lower for k in ("turnaround", "model sheet", "multiple angle", "front view", "side profile")):
                base_prompt += (
                    " Complete character master model sheet: full-body turnaround views (front view, side profile view, back view) "
                    "and a facial expression grid (neutral, smiling, confident, speaking, thoughtful) showing the same consistent face, "
                    "hairstyle, and attire from multiple angles on a single sheet on a clean studio background."
                )
            if refs and "reference image" not in p_lower and "consistent facial identity" not in p_lower:
                base_prompt += f" Maintain exact consistent facial identity, ethnicity, features, and hairstyle from reference image {refs[0].stem}."
        prompt = base_prompt.strip()
        return spec, refs, prompt

    def analyze_character_image(self, name, rel):
        """Analyze an uploaded image to verify whether it's a full character sheet (multi-angle + expressions)
        or a single face/character reference image."""
        p = self.ws.pdir(name)
        img_path = p / rel
        if not img_path.exists():
            for ext in (".png", ".jpg", ".jpeg"):
                cand = p / "stills" / f"{rel}{ext}"
                if cand.exists():
                    img_path = cand
                    break
        if not img_path.exists():
            raise ServiceError(f"image not found: {rel}")

        prompt = character_check.build_character_check_prompt()
        try:
            raw = self.ws.runner().vision(prompt, [str(img_path)], {"max_tokens": 1500, "temperature": 0.2}, project_dir=p)
            result = character_check.parse_character_analysis(raw.get("text", ""))
            result["model"] = raw.get("model", "")
            result["cost"] = raw.get("cost", 0)
        except Exception:
            # Fallback if vision model unavailable or fails
            result = dict(character_check._FALLBACK_ANALYSIS)
        result["file"] = rel
        return result
