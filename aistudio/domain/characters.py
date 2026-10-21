"""Character domain: character image prompt building, reference linking, and vision analysis."""
from pathlib import Path

from aistudio import character_check, costlog
from aistudio.domain.common import ServiceError


def resolve_character_image(p, rel):
    """Resolve a character image without allowing a path outside the project."""
    raw = str(rel or "")
    try:
        direct = (p / raw).resolve()
        direct.relative_to(p.resolve())
    except (OSError, ValueError):
        raise ServiceError("image path must stay inside the project") from None
    candidates = [direct]
    candidates += [(p / "stills" / f"{raw}{ext}").resolve() for ext in (".png", ".jpg", ".jpeg")]
    for candidate in candidates:
        try:
            candidate.relative_to(p.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    raise ServiceError(f"image not found: {rel}")


SHEET_VIEWS = ("front", "three-quarter", "profile", "full-body", "expression")
VIEW_PROMPTS = {      # view -> (prompt, aspect ratio)
    "front": ("Front view portrait of the character, head and shoulders, neutral expression, looking at the camera.", "1:1"),
    "three-quarter": ("Three-quarter view portrait of the character, head and shoulders, neutral expression.", "1:1"),
    "profile": ("Side profile view portrait of the character, head and shoulders, neutral expression.", "1:1"),
    "full-body": ("Full-body standing view of the character, head to feet, relaxed pose, facing the camera.", "9:16"),
    "expression": ("Close portrait of the character with a clear, natural smile.", "1:1"),
}
ROLE_ORDER = {"character": 0, "location": 1, "style": 2, "product": 3}      # plan 15 order: what gets cut last first
CLOSE = ("close-up", "extreme-close-up", "medium-close", "insert")
WIDE = ("extreme-wide", "wide", "medium-wide")
# preferred identity views per framing: faces for close-ups, full body for wide shots
VIEW_PREFERENCE = {"close": ("front", "expression", "three-quarter", "profile"),
                   "wide": ("full-body", "front", "three-quarter"),
                   "mid": ("three-quarter", "front", "full-body", "profile")}


def pick_refs(shot, profile, images=None, root=None):
    """-> (kept, dropped): the references a shot sends, cut to profile.references.max.

    Each ref is {id, role, path}. A character with identity-sheet views contributes the view that fits direction.framing (plus a second
    one, ranked last so it is the first thing cut); a character without views contributes its master image as before. Order: characters,
    location, style, product (plan 15), then the extra character views; `dropped` lists what the limit cut. With `root`, views whose
    file is not made yet are ignored."""
    by = {i.get("id"): i for i in (images or {}).get("images", []) if i.get("id")}
    framing = (shot.get("direction") or {}).get("framing")
    pref = VIEW_PREFERENCE["close" if framing in CLOSE else "wide" if framing in WIDE else "mid"]
    main, extra = [], []
    for ref in shot.get("refs") or []:
        rid = ref.get("id") if isinstance(ref, dict) else str(ref)
        asset = by.get(rid, {})
        kind = asset.get("kind", "other")
        role = ref.get("role") if isinstance(ref, dict) else None
        role = role or ("character" if kind == "character" else "location" if kind == "background"
                        else asset.get("role") if asset.get("role") in ROLE_ORDER else "style")
        if role not in ROLE_ORDER:
            role = "style"
        path = asset.get("out") or (ref.get("path") if isinstance(ref, dict) else rid)
        views = sorted((v for v in asset.get("views") or [] if v.get("view") in pref and v.get("file")
                        and (root is None or (Path(root) / v["file"]).is_file())), key=lambda v: pref.index(v["view"]))
        if role == "character" and views:
            main.append({"id": views[0]["id"], "role": role, "path": views[0]["file"]})
            extra += [{"id": v["id"], "role": role, "path": v["file"]} for v in views[1:2]]
        else:
            main.append({"id": rid, "role": role, "path": path})
    main.sort(key=lambda r: ROLE_ORDER[r["role"]])
    refs = main + extra
    limit = (profile.get("references") or {}).get("max", len(refs))
    return refs[:limit], refs[limit:]


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
        """Create a character-review proposal; analysis runs only after human approval."""
        p = self.ws.pdir(name)
        img_path = resolve_character_image(p, rel)
        return self.ws.propose(name, "review", img_path.stem, options={
            "review_type": "character", "file": img_path.relative_to(p.resolve()).as_posix(),
        })

    def identity_sheet(self, name, char_id, views=None, actor="local"):
        """A batch (awaiting approval, nothing approved or spent) of image proposals for the character's missing identity views, each
        conditioned on the master image. Every view is its own image asset, so it has its own price, request hash, grant and cost-log row;
        batch total == sum of items. Raises when the master is not made yet or no view is missing."""
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "images.json", {"images": []})
        char = next((i for i in doc["images"] if i.get("id") == char_id and i.get("kind") == "character"), None)
        if char is None:
            raise ServiceError(f"unknown character {char_id}")
        if not (p / char["out"]).is_file():
            raise ServiceError(f"make the master image of {char_id} first (or upload one); the views are generated from it")
        wanted = list(views or SHEET_VIEWS)
        bad = [v for v in wanted if v not in VIEW_PROMPTS]
        if bad:
            raise ServiceError(f"unknown view {', '.join(bad)}; use: {', '.join(VIEW_PROMPTS)}")
        have = {v.get("view") for v in char.get("views") or [] if (p / v.get("file", "")).is_file()}
        missing = [v for v in dict.fromkeys(wanted) if v not in have]
        if not missing:
            raise ServiceError(f"{char_id} already has these views")
        known = {i["id"]: i for i in doc["images"]}
        items = []
        for view in missing:
            vid = f"{char_id}_{view.replace('-', '_')}"
            if vid not in known:
                doc["images"].append({"id": vid, "kind": "other", "out": f"stills/{vid}.png", "refs": [char_id], "aspect_ratio": VIEW_PROMPTS[view][1],
                                      "prompt": f"{VIEW_PROMPTS[view][0]} Same person as the reference image {char_id}: identical face, hair, skin tone and outfit. "
                                                f"Plain neutral studio background. {char.get('prompt', '')}".strip()[:1200]})
            views_list = char.setdefault("views", [])
            if not any(v.get("id") == vid for v in views_list):
                views_list.append({"id": vid, "view": view, "file": f"stills/{vid}.png"})
            items.append({"kind": "image", "target": vid, "label": f"{char_id} {view}"})
        self.ws.put_images(name, doc)
        for it in items:      # same resolver as propose/execute, after the assets exist
            it["price"], it["model"] = self.ws.pipeline_domain._item_price(p, "image", it["target"])
        b = self.ws._read(p, "budget.json", {})
        plan = {"items": items, "total": round(sum(i["price"] for i in items), 6),
                "budget": {"estimate": b.get("estimate"), "stop_loss": b.get("stop_loss"), "spent": round(costlog.spent(p), 6)}}
        return self.ws.batches.create(name, actor=actor, plan=plan)
