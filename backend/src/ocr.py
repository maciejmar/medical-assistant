"""OCR zdjęć stron (Tesseract, lokalnie – obrazy nie opuszczają serwera).

Odczytywany jest wyłącznie druk: słowa poniżej progu pewności (OCR_MIN_WORD_CONFIDENCE) są
odrzucane, a pismo odręczne Tesseract rozpoznaje z niską pewnością, więc w praktyce odpada.
Obrócone zdjęcia (np. strona sfotografowana bokiem) są wykrywane przez porównanie pewności
rozpoznania w czterech orientacjach.

Wymaga programu tesseract z danymi języka polskiego (w obrazie Dockera: tesseract-ocr-pol).
"""

import io
from dataclasses import dataclass
from typing import Any

import pytesseract
from PIL import Image, ImageOps

from .config import settings

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

_PROBE_SIDE_PX = 1600
_GOOD_ENOUGH_CONFIDENCE = 75.0
_MIN_WORDS_FOR_ORIENTATION = 15


class OcrUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float  # średnia pewność zachowanych słów (0–100)
    words: int


def lines_from_data(data: dict[str, list[Any]], min_confidence: int) -> OcrResult:
    """Składa tekst z wyniku image_to_data: zachowuje słowa o pewności >= progu, a linię tylko
    wtedy, gdy większość jej słów jest pewna (linie odręczne/zaszumione znikają w całości)."""
    lines: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append((word, conf))

    paragraphs: list[list[str]] = []
    previous_paragraph: tuple[int, int] | None = None
    kept_confidences: list[float] = []
    for key in sorted(lines):
        words = lines[key]
        confident = [(w, c) for w, c in words if c >= min_confidence]
        if len(confident) * 2 < len(words) or sum(len(w) for w, _ in confident) < 2:
            continue
        text = " ".join(w for w, _ in confident)
        if (key[0], key[1]) != previous_paragraph:
            paragraphs.append([])
            previous_paragraph = (key[0], key[1])
        paragraphs[-1].append(text)
        kept_confidences.extend(c for _, c in confident)

    text = "\n\n".join("\n".join(p) for p in paragraphs if p)
    confidence = sum(kept_confidences) / len(kept_confidences) if kept_confidences else 0.0
    return OcrResult(text=text, confidence=round(confidence, 1), words=len(kept_confidences))


def _resized(image: Image.Image, max_side: int) -> Image.Image:
    image = image.copy()
    image.thumbnail((max_side, max_side))
    return image


def _read(image: Image.Image) -> OcrResult:
    data = pytesseract.image_to_data(
        image,
        lang=settings.ocr_languages,
        config="--psm 3",
        output_type=pytesseract.Output.DICT,
    )
    return lines_from_data(data, settings.ocr_min_word_confidence)


def best_rotation(probe: Image.Image) -> int:
    """Kąt (0/90/180/270), przy którym rozpoznanie jest najpewniejsze."""
    upright = _read(probe)
    if (
        upright.words >= _MIN_WORDS_FOR_ORIENTATION
        and upright.confidence >= _GOOD_ENOUGH_CONFIDENCE
    ):
        return 0
    scores = {0: upright.confidence * upright.words}
    for angle in (90, 270, 180):
        result = _read(probe.rotate(angle, expand=True))
        scores[angle] = result.confidence * result.words
    return max(scores, key=lambda angle: scores[angle])


def ocr_image(data: bytes) -> OcrResult:
    """Rozpoznaje druk na zdjęciu strony. Operacja blokująca (CPU) – wywoływać w wątku."""
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
    except Exception as exc:
        raise ValueError(f"Nie udało się otworzyć obrazu: {exc}") from exc
    try:
        angle = best_rotation(_resized(image, _PROBE_SIDE_PX))
        page = _resized(image, settings.ocr_max_side_px)
        return _read(page.rotate(angle, expand=True) if angle else page)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "Brak programu tesseract na serwerze (obraz Dockera: tesseract-ocr, tesseract-ocr-pol)."
        ) from exc
