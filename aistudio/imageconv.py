"""Accept common image formats and normalise them to PNG or JPEG (what the image/video models take). Standard library only.

Detection is by the file's own bytes (never the filename). PNG and JPEG pass through untouched. GIF, BMP, TIFF, WebP and HEIC/HEIF are converted
with macOS `sips` if present, else Pillow if installed. If neither exists the upload is refused with a clear message. No shell is used; files
go through a private temp folder.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path


class ImageError(Exception):
    pass


MAX_BYTES = 25_000_000


def detect(data):
    """Return one of png, jpg, gif, bmp, tiff, webp, heic, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:2] == b"BM" and len(data) > 26:
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis"):
        return "heic"
    return None


def _convert_sips(data, kind, which):
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / f"in.{kind}", Path(d) / "out.png"
        src.write_bytes(data)
        r = subprocess.run([which, "-s", "format", "png", str(src), "--out", str(dst)], capture_output=True, timeout=60)
        if r.returncode != 0 or not dst.exists():
            raise ImageError(f"could not convert the {kind} image")
        return dst.read_bytes()


def _convert_pillow(data, kind):
    import io
    from PIL import Image  # optional dependency
    im = Image.open(io.BytesIO(data))
    im.load()
    out = io.BytesIO()
    im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG")
    return out.getvalue()


def normalise(data, which=shutil.which):
    """Return (bytes, ext) with ext 'png' or 'jpg'. Raises ImageError if the bytes are not a supported image."""
    if not data or len(data) > MAX_BYTES:
        raise ImageError("the image is empty or larger than 25 MB")
    kind = detect(data)
    if kind is None:
        raise ImageError("that file is not a supported image (use PNG, JPEG, WebP, GIF, BMP, TIFF or HEIC)")
    if kind in ("png", "jpg"):
        return data, kind
    sips = which("sips")
    if sips:
        return _convert_sips(data, kind, sips), "png"
    try:
        return _convert_pillow(data, kind), "png"
    except ImportError:
        raise ImageError(f"this computer cannot convert {kind} images; please save it as PNG or JPEG first") from None
    except Exception:
        raise ImageError(f"could not read the {kind} image") from None
