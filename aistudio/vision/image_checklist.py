"""V2: vision review of a generated STILL IMAGE. Standard library only.

Contract (tests in tests/test_image_checklist.py):
  IMAGE_CHECKLIST: list[str]  exactly these 6 strings in this order:
     "The person looks like the same person as in the character reference image."
     "The place looks like the same place as in the background reference image."
     "No extra or unknown person appears."
     "No garbled text, no watermark, no logos."
     "No distorted face, hands or body."
     "The framing is vertical 9:16 and the main subject is fully visible."
  build_prompt(img: dict, refs: list[str]) -> str
     A vision-model instruction that names img["id"], states the kind (img.get("kind")), lists the reference file names from `refs`
     (or says "none"), numbers the IMAGE_CHECKLIST 1..6, and demands ONLY a JSON object
     {"verdict":"pass|warn|fail","findings":[{"frame":0,"issue":str,"severity":"low|medium|high"}],"summary":str}.
  parse_review  is the SAME function as aistudio.vision.clip_checklist.parse_review (import and re-export it).
"""
from aistudio.vision.clip_checklist import parse_review  # re-export

IMAGE_CHECKLIST = [
    "The person looks like the same person as in the character reference image.",
    "The place looks like the same place as in the background reference image.",
    "No extra or unknown person appears.",
    "No garbled text, no watermark, no logos.",
    "No distorted face, hands or body.",
    "The framing is vertical 9:16 and the main subject is fully visible.",
]


def build_prompt(img, refs):
    ref_list = ", ".join(refs) if refs else "none"
    lines = [
        f"Review the still image with id \"{img['id']}\" (kind: {img.get('kind')}).",
        f"Reference images: {ref_list}",
        "Check each item below and report any issues:",
    ]
    lines += [f"{i}. {item}" for i, item in enumerate(IMAGE_CHECKLIST, 1)]
    lines.append(
        'Respond with ONLY a JSON object of the form '
        '{"verdict":"pass|warn|fail","findings":[{"frame":0,"issue":str,"severity":"low|medium|high"}],"summary":str}.'
    )
    return "\n".join(lines)
