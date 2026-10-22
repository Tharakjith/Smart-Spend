"""Text extraction: embedded PDF text first, OCR for scans and images.

OCR providers (OCR_PROVIDER):
  auto      - Tesseract if installed, otherwise RapidOCR if its package is installed (default)
  tesseract - system Tesseract (installed in the Docker image)
  rapidocr  - RapidOCR (pip package with bundled ONNX models; no system install, works on Windows)
  none      - disabled; images go to manual entry
"""
import io
import math
import logging
import shutil
import statistics
import threading
import unicodedata

from PIL import Image, ImageOps

from app.core.config import get_settings

log = logging.getLogger("smartspend.ocr")

MAX_SIDE = 2400  # large phone photos are downscaled for speed; text stays legible


class OcrUnavailable(Exception):
    pass


def _tesseract_available() -> bool:
    s = get_settings()
    return bool(s.tesseract_cmd or shutil.which("tesseract"))


def _rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_provider() -> str | None:
    p = get_settings().ocr_provider
    if p == "none":
        return None
    if p == "tesseract":
        return "tesseract" if _tesseract_available() else None
    if p == "rapidocr":
        return "rapidocr" if _rapidocr_available() else None
    if _tesseract_available():
        return "tesseract"
    if _rapidocr_available():
        return "rapidocr"
    return None


def ocr_available() -> bool:
    return ocr_provider() is not None


def _prepare(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")  # honour phone rotation
    longest = max(img.size)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    elif img.width < 1000:  # small screenshots OCR better upscaled
        img = img.resize((img.width * 2, img.height * 2))
    return img


def _tesseract(img: Image.Image) -> str:
    import pytesseract

    s = get_settings()
    if s.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = s.tesseract_cmd
    return pytesseract.image_to_string(img.convert("L"), config="--psm 6")


_rapid_engine = None
_rapid_lock = threading.Lock()


def _rapid_boxes(img: Image.Image) -> list:
    global _rapid_engine
    from rapidocr_onnxruntime import RapidOCR

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with _rapid_lock:  # the engine is loaded once and is not guaranteed thread-safe
        if _rapid_engine is None:
            _rapid_engine = RapidOCR()
        result, _ = _rapid_engine(buf.getvalue())
    # Text running vertically (margin slogans, rotated stamps) is never the bill's main content and would be
    # merged into neighbouring lines.
    return [r for r in (result or []) if not _is_vertical(r[0])]


def _is_vertical(box) -> bool:
    (x0, y0), (x1, y1), (x2, y2) = box[0], box[1], box[2]
    width = math.hypot(x1 - x0, y1 - y0)
    height = math.hypot(x2 - x1, y2 - y1)
    return height > 1.5 * width


def _rapidocr(img: Image.Image) -> str:
    return boxes_to_text(_rapid_boxes(img))


def text_angles(img: Image.Image) -> list[float]:
    """Angles (degrees) at which text runs in different parts of a photo; curled paper has more than one."""
    angles = []
    for box, text, _ in _rapid_boxes(img):
        (x0, y0), (x1, y1) = box[0], box[1]
        if x1 - x0 > 40 and len(str(text)) >= 3:
            angles.append(math.degrees(math.atan2(y1 - y0, x1 - x0)))
    return sorted(angles)


def retry_texts(data: bytes, content_type: str, max_passes: int = 2) -> list[str]:
    """Second-chance OCR for photos of curled or folded bills.

    Re-reads the image straightened to the steepest text angles found in it (e.g. the bottom of a folded
    receipt). Only meaningful for images read with RapidOCR; returns [] otherwise.
    """
    if content_type == "application/pdf" or ocr_provider() != "rapidocr":
        return []
    img = _prepare(Image.open(io.BytesIO(data)))
    angles = text_angles(img)
    if len(angles) < 5:
        return []
    candidates = []
    for q in (0.9, 0.1):  # the most tilted regions in each direction
        a = angles[min(len(angles) - 1, int(q * len(angles)))]
        if abs(a) >= 5 and all(abs(a - c) >= 5 for c in candidates):
            candidates.append(a)
    texts = []
    for a in candidates[:max_passes]:
        rotated = img.rotate(a, expand=True, fillcolor="white")
        texts.append(unicodedata.normalize("NFKC", _rapidocr(rotated)))
    return texts


def boxes_to_text(result: list) -> str:
    """Rebuilds reading-order lines from OCR boxes ([box, text, score]).

    Boxes whose vertical centres are close belong to one printed line; they are joined left to right with a
    wide gap so the receipt parser can still tell item names, quantities, prices and totals apart.
    """

    # Photos are rarely perfectly level. A 2° tilt across a receipt shifts the right-hand column by a whole
    # line, pairing "Sub Total" with the discount's amount. Estimate the tilt from the boxes' top edges and
    # group along the tilted axis instead of the image's horizontal.
    slopes = []
    for box, _text, _score in result:
        (x0, y0), (x1, y1) = box[0], box[1]
        width, height = x1 - x0, abs(box[3][1] - box[0][1]) or 1
        if width > 2 * height:  # short boxes give unreliable angles
            slopes.append((y1 - y0) / width)
    tilt = statistics.median(slopes) if slopes else 0.0
    if abs(math.degrees(math.atan(tilt))) > 15:  # not a tilt but a rotated image; leave it to the engine
        tilt = 0.0
    items = []
    for box, text, _score in result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        xc, yc = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        items.append({"y": yc - tilt * xc, "h": (max(ys) - min(ys)) / math.sqrt(1 + tilt * tilt), "x": min(xs), "text": str(text).strip()})
    if not items:
        return ""
    tol = 0.6 * statistics.median(i["h"] for i in items)
    items.sort(key=lambda i: i["y"])
    lines: list[list[dict]] = []
    for it in items:
        if lines and abs(it["y"] - statistics.fmean(i["y"] for i in lines[-1])) <= tol:
            lines[-1].append(it)
        else:
            lines.append([it])
    return "\n".join("    ".join(i["text"] for i in sorted(line, key=lambda i: i["x"])) for line in lines)


def _ocr_image(img: Image.Image) -> str:
    provider = ocr_provider()
    if provider is None:
        raise OcrUnavailable("Images need OCR, and no OCR engine is installed on this server.")
    img = _prepare(img)
    text = _tesseract(img) if provider == "tesseract" else _rapidocr(img)
    # Full-width punctuation and other compatibility forms ("，", "：") become plain ASCII.
    return unicodedata.normalize("NFKC", text)


def extract_text(data: bytes, content_type: str) -> tuple[str, str]:
    """Returns (text, method). method is pdf_text | ocr. Raises OcrUnavailable if OCR is required but missing."""
    if content_type == "application/pdf":
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text("text", sort=True) for page in doc)
        if len(text.strip()) >= 20:
            return text, "pdf_text"
        if not ocr_available():
            raise OcrUnavailable("This PDF is a scan with no embedded text, and no OCR engine is installed.")
        parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=250)
            parts.append(_ocr_image(Image.open(io.BytesIO(pix.tobytes("png")))))
        return "\n".join(parts), "ocr"
    return _ocr_image(Image.open(io.BytesIO(data))), "ocr"
