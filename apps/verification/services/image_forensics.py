"""
Verification image forensics (report-only, never blocks).

Extracts triage signals from an uploaded verification image (gesture selfie or
college ID) so an admin can judge whether it looks like a genuine, unaltered
capture. Nothing here rejects an upload: a failure degrades to an "unknown"
report and the submission proceeds untouched.

Each signal carries a ``verdict``:
  - ``ok``        looks fine (admin panel renders green)
  - ``info``      neutral context / cannot tell (grey / amber)
  - ``attention`` worth a closer look, possibly forged/altered (red)

Design notes on the "scrubbed metadata" tell: a genuine photo is either full of
camera metadata OR uniformly stripped (a clean re-encode, which an in-app camera
may do). A tampered photo is usually *partial* - identifying fields surgically
removed while structural EXIF remains, or timestamps that contradict each other.
So absence alone is never flagged red (that would cry wolf on normal captures);
only selective removal / internal inconsistency / a configured-but-missing field
is. See ``EXPECTED_METADATA_FIELDS`` for the optional strict baseline.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# EXIF tag ids (avoid importing the name map; these are stable).
_TAG_MAKE = 271
_TAG_MODEL = 272
_TAG_SOFTWARE = 305
_TAG_DATETIME = 306
_TAG_ORIENTATION = 274
_IFD_EXIF = 0x8769
_IFD_GPS = 0x8825
_TAG_DATETIME_ORIGINAL = 36867
_TAG_DATETIME_DIGITIZED = 36868

# Software/ProcessingSoftware substrings that indicate the image passed through an
# editor or a generator (case-insensitive). Presence is a red flag.
EDITOR_KEYWORDS = (
    "photoshop", "lightroom", "gimp", "snapseed", "pixlr", "paint.net",
    "picsart", "facetune", "canva", "affinity", "inkscape", "photopea",
    "beautyplus", "meitu", "faceapp", "remini", "comfyui", "stable diffusion",
    "midjourney", "dall-e", "dalle", "firefly", "fotor", "retouch",
)

# Optional STRICT baseline: EXIF tag ids that a legitimate submission from our
# capture pipeline must always carry. Left empty by default so we never flag a
# normal clean-stripped capture; populate once real submissions are observed to
# turn "a field that should always be present is missing" into a red flag.
EXPECTED_METADATA_FIELDS: tuple[int, ...] = ()

# Map declared MIME to the Pillow format name(s) it should decode as.
_MIME_TO_FORMATS = {
    "image/jpeg": {"JPEG", "MPO"},
    "image/png": {"PNG"},
    "image/webp": {"WEBP"},
}

_MAX_DIM = 20000
_MIN_DIM = 200
_DATETIME_SKEW = timedelta(days=2)  # generous; absorbs timezone + clock drift


def _signal(key, label, value, verdict, note):
    return {"key": key, "label": label, "value": value, "verdict": verdict, "note": note}


def _safe_str(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace").strip("\x00 ").strip()
        return str(value).strip()
    except Exception:  # noqa: BLE001
        return ""


def _parse_exif_dt(value) -> datetime | None:
    text = _safe_str(value)
    if not text:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _dhash(img, hash_size: int = 8) -> str:
    """64-bit difference hash as 16 hex chars. Pillow-only (no numpy)."""
    gray = img.convert("L").resize((hash_size + 1, hash_size))
    pixels = list(gray.getdata())
    width = hash_size + 1
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * width + col]
            right = pixels[row * width + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def _detect_c2pa(data: bytes) -> bool:
    """Heuristic presence check for a C2PA / Content Credentials manifest (a JUMBF
    box). Presence only, not cryptographic validation (that is Phase 2)."""
    head = data[: 5_000_000]  # manifests sit near the start; cap the scan
    return b"c2pa" in head or b"jumbf" in head or b"urn:uuid:" in head and b"c2ma" in head


def analyze_image(
    data: bytes,
    *,
    declared_content_type: str = "",
    filename: str = "",
    reference_time: datetime | None = None,
) -> dict:
    """Analyze raw image bytes and return a forensic report.

    ``reference_time`` is the moment the verification attempt began (used to flag a
    selfie captured well before the gesture could have been assigned). Never raises.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    report: dict = {"overall": "ok", "sha256": sha256, "phash": "", "signals": []}
    signals = report["signals"]

    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001 — Pillow missing must not break uploads.
        logger.warning("image_forensics: Pillow unavailable: %s", exc)
        signals.append(_signal(
            "analysis", "Forensic analysis", "unavailable", "info",
            "Image analysis library unavailable; no signals computed.",
        ))
        return report

    # --- decode ---------------------------------------------------------
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001
        signals.append(_signal(
            "decodable", "Valid image", "no", "attention",
            f"File did not decode as a valid image ({type(exc).__name__}).",
        ))
        report["overall"] = "attention"
        return report
    signals.append(_signal("decodable", "Valid image", "yes", "ok",
                           "Decodes as a valid image."))

    fmt = (img.format or "").upper()
    width, height = img.size

    # --- perceptual hash ------------------------------------------------
    try:
        report["phash"] = _dhash(img)
    except Exception as exc:  # noqa: BLE001
        logger.debug("image_forensics: phash failed: %s", exc)

    # --- declared type vs real format ----------------------------------
    declared = (declared_content_type or "").lower()
    expected_formats = _MIME_TO_FORMATS.get(declared)
    if not declared:
        signals.append(_signal("format", "File format", fmt or "unknown", "info",
                               "No declared content type to compare."))
    elif expected_formats and fmt in expected_formats:
        signals.append(_signal("format", "File format", fmt, "ok",
                               f"Real format matches the declared type ({declared})."))
    else:
        signals.append(_signal(
            "format", "File format", f"{fmt} (declared {declared})", "attention",
            "The actual file format does not match the declared content type.",
        ))

    # --- dimensions -----------------------------------------------------
    dims = f"{width}x{height}"
    aspect = (width / height) if height else 0
    if _MIN_DIM <= min(width, height) and max(width, height) <= _MAX_DIM and 0.2 <= aspect <= 5:
        signals.append(_signal("dimensions", "Dimensions", dims, "ok",
                               "Dimensions are within a normal camera range."))
    else:
        signals.append(_signal("dimensions", "Dimensions", dims, "info",
                               "Unusual dimensions for a phone photo."))

    # --- EXIF gather ----------------------------------------------------
    exif = {}
    exif_ifd = {}
    gps_ifd = {}
    try:
        exif = dict(img.getexif())
        try:
            exif_ifd = dict(img.getexif().get_ifd(_IFD_EXIF))
        except Exception:  # noqa: BLE001
            exif_ifd = {}
        try:
            gps_ifd = dict(img.getexif().get_ifd(_IFD_GPS))
        except Exception:  # noqa: BLE001
            gps_ifd = {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("image_forensics: exif read failed: %s", exc)

    make = _safe_str(exif.get(_TAG_MAKE))
    model = _safe_str(exif.get(_TAG_MODEL))
    software = _safe_str(exif.get(_TAG_SOFTWARE))
    dt_main = _safe_str(exif.get(_TAG_DATETIME))
    dt_original = _safe_str(exif_ifd.get(_TAG_DATETIME_ORIGINAL))
    has_any_exif = bool(exif) or bool(exif_ifd) or bool(gps_ifd)

    # --- editor fingerprint --------------------------------------------
    sw_lower = software.lower()
    editor_hit = next((kw for kw in EDITOR_KEYWORDS if kw in sw_lower), None)
    if editor_hit:
        signals.append(_signal(
            "editor", "Editing software", software, "attention",
            f"Image metadata names an editor/generator ('{editor_hit}').",
        ))
    elif software:
        signals.append(_signal("editor", "Editing software", software, "info",
                               "Software tag present (looks like a device/OS, not an editor)."))
    else:
        signals.append(_signal("editor", "Editing software", "none", "ok",
                               "No editing-software tag."))

    # --- metadata integrity (scrub / inconsistency detection) ----------
    present_fields = _present_field_names(exif, exif_ifd, gps_ifd)
    if not has_any_exif:
        signals.append(_signal(
            "metadata_integrity", "Metadata integrity", "no metadata", "info",
            "No embedded metadata. Consistent with a clean re-encode on capture; "
            "absence alone does not prove tampering.",
        ))
    else:
        issues = []
        structural = [t for t in exif if t not in (_TAG_MAKE, _TAG_MODEL, _TAG_SOFTWARE, _TAG_DATETIME)]
        # Selective scrub: EXIF structure remains but all identifying fields gone.
        if structural and not make and not model and not dt_original:
            issues.append("identifying fields (Make/Model/DateTimeOriginal) removed "
                          "while other EXIF remains")
        # Contradictory timestamps (editor re-saved DateTime, left DateTimeOriginal).
        d1, d2 = _parse_exif_dt(dt_main), _parse_exif_dt(dt_original)
        if d1 and d2 and abs(d1 - d2) > _DATETIME_SKEW:
            issues.append("DateTime and DateTimeOriginal are far apart")
        # Optional strict baseline: a field that must always be present is missing.
        for tag in EXPECTED_METADATA_FIELDS:
            if tag not in exif and tag not in exif_ifd:
                issues.append(f"expected metadata field {tag} is missing")
        if issues:
            signals.append(_signal(
                "metadata_integrity", "Metadata integrity", "altered", "attention",
                "Metadata looks altered: " + "; ".join(issues) + ".",
            ))
        else:
            signals.append(_signal(
                "metadata_integrity", "Metadata integrity", "consistent", "ok",
                "Embedded metadata is present and internally consistent.",
            ))

    # --- capture time vs attempt ---------------------------------------
    cap = _parse_exif_dt(dt_original) or _parse_exif_dt(dt_main)
    if cap is None:
        signals.append(_signal("capture_time", "Capture time", "unknown", "info",
                               "No capture timestamp in metadata."))
    else:
        now = datetime.utcnow()
        ref = reference_time.replace(tzinfo=None) if reference_time else None
        if cap > now + _DATETIME_SKEW:
            signals.append(_signal("capture_time", "Capture time", cap.isoformat(),
                                   "attention", "Capture time is in the future."))
        elif ref is not None and cap < ref - _DATETIME_SKEW:
            signals.append(_signal(
                "capture_time", "Capture time", cap.isoformat(), "attention",
                "Photo was captured well before this verification attempt began.",
            ))
        else:
            signals.append(_signal("capture_time", "Capture time", cap.isoformat(),
                                   "ok", "Capture time is consistent with the attempt."))

    # --- device / GPS / C2PA (informational) ---------------------------
    device = " ".join(p for p in (make, model) if p)
    signals.append(_signal("device", "Capture device", device or "unknown", "info",
                           "Device make/model from metadata." if device else
                           "No device make/model in metadata."))
    signals.append(_signal(
        "gps", "Location metadata", "present" if gps_ifd else "none", "info",
        "Location metadata present (coordinates not shown)." if gps_ifd
        else "No location metadata.",
    ))
    if _detect_c2pa(data):
        signals.append(_signal("c2pa", "Content Credentials (C2PA)", "present", "ok",
                               "A C2PA provenance manifest is present (presence only)."))
    else:
        signals.append(_signal("c2pa", "Content Credentials (C2PA)", "absent", "info",
                               "No C2PA provenance manifest."))

    signals.append(_signal("metadata_profile", "Metadata fields", present_fields, "info",
                           "Metadata fields found in the file (fingerprint)."))

    if any(s["verdict"] == "attention" for s in signals):
        report["overall"] = "attention"
    return report


def _present_field_names(exif: dict, exif_ifd: dict, gps_ifd: dict) -> list[str]:
    names = []
    name_map = {
        _TAG_MAKE: "Make", _TAG_MODEL: "Model", _TAG_SOFTWARE: "Software",
        _TAG_DATETIME: "DateTime", _TAG_ORIENTATION: "Orientation",
        _TAG_DATETIME_ORIGINAL: "DateTimeOriginal",
        _TAG_DATETIME_DIGITIZED: "DateTimeDigitized",
    }
    for tag, label in name_map.items():
        if exif.get(tag) or exif_ifd.get(tag):
            names.append(label)
    if gps_ifd:
        names.append("GPS")
    return sorted(names)
