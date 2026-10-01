"""Main colours of an image (for example a logo), so a brand-colour style can be written into the storyboard.  Needs Pillow; without it
dominant_colors returns [].  Standard library + Pillow."""
from collections import defaultdict
from pathlib import Path


def dominant_colors(path, n=4):
    """Up to n hex colours ('#rrggbb'), most common first.  Transparent, near-white and near-black pixels are ignored unless nothing else is left.
    A flat colour comes back exactly; similar shades are grouped and averaged."""
    try:
        from PIL import Image
    except ImportError:
        return []
    try:
        im = Image.open(Path(path)).convert("RGBA")
    except Exception:
        return []
    im.thumbnail((96, 96))
    data = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
    px = [p[:3] for p in data if p[3] > 200]
    if not px:
        return []
    keep = [p for p in px if not (min(p) > 235 or max(p) < 20)] or px
    buckets = defaultdict(list)
    for r, g, b in keep:
        buckets[(r >> 5, g >> 5, b >> 5)].append((r, g, b))          # 8 levels per channel: similar shades share a bucket
    out, total = [], float(len(keep))
    for _, pts in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        if out and len(pts) / total < 0.04:
            break
        r, g, b = (round(sum(c[i] for c in pts) / len(pts)) for i in range(3))
        if all(abs(r - int(h[1:3], 16)) + abs(g - int(h[3:5], 16)) + abs(b - int(h[5:7], 16)) > 60 for h in out):
            out.append("#%02x%02x%02x" % (r, g, b))
        if len(out) >= n:
            break
    return out
