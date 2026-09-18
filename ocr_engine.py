"""
ocr_engine.py
=============
Text extraction + route-number parsing.

ENGINE CHOICE: Tesseract is the default and the only one recommended for
the Pi Zero 2 W. EasyOCR is included as an optional path because it's
commonly suggested for this kind of project, but it depends on PyTorch,
which on a Zero 2 W (512MB RAM, no GPU) typically costs 2-4 seconds just
to load the model on cold start and 500ms-1.5s per inference even warm —
that alone can consume the entire 1.5s budget before you've done
anything else. Tesseract's `--psm 7` single-line mode on a small, high-
contrast, binarized crop typically runs in 100-400ms on this hardware.

If you later move to a Pi 4/5 or add a Coral/Hailo accelerator, EasyOCR
(or a PaddleOCR-lite model) becomes a reasonable accuracy upgrade — see
SOFTWARE_AND_HARDWARE_GUIDE.md.
"""
import re
import time
import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import pytesseract

import config

logger = logging.getLogger("bus_route.ocr")
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

_ROUTE_PATTERN = re.compile(config.ROUTE_REGEX)


@dataclass
class OcrResult:
    raw_text: str
    route: Optional[str]
    confidence: float  # 0-100
    engine: str
    elapsed_s: float
    # True when `confidence` is a stand-in, not a real measurement (e.g. Windows'
    # OCR API returns no confidence score at all). The UI must label these
    # differently from Tesseract's genuine per-word confidence — never present
    # an estimate as if it were a measured percentage.
    confidence_is_estimated: bool = False


_paddle_engine = None
_paddle_init_failed = False


def _get_paddle_engine():
    global _paddle_engine, _paddle_init_failed
    if _paddle_init_failed:
        return None
    if _paddle_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _paddle_engine = RapidOCR()
            logger.info("PaddleOCR (PP-OCRv4 ONNX Runtime) initialized successfully.")
        except Exception as e:
            # Latch the failure. Retrying the import on every button press costs
            # time on the hot path and floods the log with the same warning.
            _paddle_init_failed = True
            logger.warning("PaddleOCR initialization failed: %s", e)
            return None
    return _paddle_engine


def _detection_height(box) -> float:
    try:
        ys = [float(p[1]) for p in box]
        return max(ys) - min(ys)
    except Exception:
        return 0.0


def _score_candidate(route: str, text: str, conf: float, rel_height: float) -> float:
    """Rank how likely a route token found in `text` is the actual route board.

    A route board is typically the largest text in frame, read confidently, and
    standing alone or leading its line ("55K", "231 AUTO NAGAR"). A route-shaped
    token buried mid-string is usually part of an ad, a plate, or a slogan.
    """
    compact = re.sub(r"[^A-Z0-9/]", "", text.upper())
    score = conf + 0.25 * rel_height
    if compact == route:
        score += 0.35
    elif compact.startswith(route):
        score += 0.15
    if re.search(config.PLATE_REGEX, text.upper()):
        score -= 0.40
    return score


def _select_best_route(detections, frame_height: int):
    """Pick the most plausible route from per-detection OCR output.

    `detections` is a list of (text, confidence 0-1, box). Returns
    (route, confidence 0-100) where the confidence belongs to the winning
    detection — averaging every detection in the frame would let a dozen
    shopfront signs drown out a cleanly-read route board.
    """
    best = None
    best_score = float("-inf")
    heights = [_detection_height(b) for _, _, b in detections]
    tallest = max(heights) if heights else 0.0

    for (text, conf, _box), height in zip(detections, heights):
        rel_height = (height / tallest) if tallest else 0.0
        for route in _route_tokens(text):
            score = _score_candidate(route, text, conf, rel_height)
            if score > best_score:
                best_score, best = score, (route, conf * 100.0)

    return best if best else (None, 0.0)


def _extract_with_paddleocr(frame: np.ndarray) -> OcrResult:
    t0 = time.monotonic()
    engine = _get_paddle_engine()
    if engine is None:
        return OcrResult("", None, 0.0, "paddleocr_unavailable", time.monotonic() - t0)

    try:
        h, w = frame.shape[:2]
        max_dim = max(h, w)
        if max_dim > config.OCR_MAX_DIM:
            scale = config.OCR_MAX_DIM / max_dim
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        res, _ = engine(frame)
        if not res:
            return OcrResult("", None, 0.0, "paddleocr", time.monotonic() - t0)

        detections = [(line[1].strip(), float(line[2]), line[0]) for line in res if line[1].strip()]
        route, confidence = _select_best_route(detections, frame.shape[0])
        raw_text = " ".join(text for text, _, _ in detections)

        return OcrResult(raw_text, route, confidence, "paddleocr", time.monotonic() - t0)
    except Exception as e:
        logger.error("PaddleOCR extraction error: %s", e, exc_info=True)
        return OcrResult("", None, 0.0, "paddleocr_error", time.monotonic() - t0)


def extract_route(binary_image: np.ndarray, raw_frame: Optional[np.ndarray] = None) -> OcrResult:
    """Run OCR + regex parsing, returning the best route match found."""
    frame_to_use = raw_frame if raw_frame is not None else binary_image

    if config.OCR_ENGINE == "paddleocr":
        res = _extract_with_paddleocr(frame_to_use)
        if res.engine not in ("paddleocr_unavailable", "paddleocr_error"):
            return res
        logger.info("PaddleOCR unavailable. Falling back to Tesseract...")

    if config.OCR_ENGINE == "easyocr":
        return _extract_with_easyocr(binary_image)

    return _extract_with_tesseract(binary_image, raw_frame=raw_frame)


def _tesseract_pass(binary_image: np.ndarray, psm: int):
    tess_config = (
        f"--psm {psm} -c tessedit_char_whitelist={config.TESSERACT_WHITELIST}"
    )
    data = pytesseract.image_to_data(
        binary_image,
        lang=config.TESSERACT_LANG,
        config=tess_config,
        output_type=pytesseract.Output.DICT,
    )
    words, confidences = [], []
    for text, conf in zip(data["text"], data["conf"]):
        conf = float(conf)
        if text.strip() and conf >= 0:
            words.append(text.strip())
            confidences.append(conf)
    raw_text = " ".join(words)
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return raw_text, mean_conf


def _extract_with_winocr(binary_image: np.ndarray, raw_frame: Optional[np.ndarray] = None) -> OcrResult:
    t0 = time.monotonic()
    try:
        import winocr
        texts = []

        # Pass 1: Raw image (best for natural text, signs, color boards)
        if raw_frame is not None and raw_frame.size > 0:
            res_raw = winocr.recognize_cv2_sync(raw_frame)
            if res_raw and res_raw.get("text"):
                texts.append(res_raw["text"].strip())

            # Pass 1b: 2x scaled for small fonts / window signs
            h_f, w_f = raw_frame.shape[:2]
            if max(h_f, w_f) < 1200:
                scale = min(2.0, 1600.0 / max(h_f, w_f))
                frame_scaled = cv2.resize(raw_frame, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                res_scaled = winocr.recognize_cv2_sync(frame_scaled)
                if res_scaled and res_scaled.get("text"):
                    texts.append(res_scaled["text"].strip())

        # Pass 2: Binary threshold image (best for high-contrast white-on-black or black-on-white plates)
        if binary_image is not None and binary_image.size > 0:
            img_bgr = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR) if binary_image.ndim == 2 else binary_image.copy()
            res_bin = winocr.recognize_cv2_sync(np.ascontiguousarray(img_bgr))
            if res_bin and res_bin.get("text"):
                texts.append(res_bin["text"].strip())

        # Deduplicate and combine lines
        combined_lines = []
        seen = set()
        for block in texts:
            for line in block.split("\n"):
                clean_l = line.strip()
                if clean_l and len(clean_l) >= 2 and clean_l.lower() not in seen:
                    seen.add(clean_l.lower())
                    combined_lines.append(clean_l)

        raw_text = " ".join(combined_lines)
        route = _parse_route(raw_text)

        # Windows' OCR API (winrt OcrEngine) does not expose any confidence
        # score — there is no real number to report here. Rather than
        # fabricate a specific percentage (which was misleading: it made an
        # unreliable read look precisely measured), report a plain pass/fail
        # signal tied to whether a well-formed route pattern was actually
        # found, and flag it as estimated so the UI never displays it as a
        # genuine measured confidence.
        mean_conf = (config.OCR_MIN_CONFIDENCE + 10.0) if route else 0.0
        elapsed = time.monotonic() - t0
        logger.debug("winocr raw='%s' route=%s estimated_conf=%.1f (%.3fs)", raw_text, route, mean_conf, elapsed)
        return OcrResult(raw_text, route, mean_conf, "winocr", elapsed, confidence_is_estimated=True)
    except Exception as e:
        logger.warning("winocr extraction failed: %s", e)
        return OcrResult("", None, 0.0, "winocr", time.monotonic() - t0, confidence_is_estimated=True)



def _extract_with_tesseract(binary_image: np.ndarray, raw_frame: Optional[np.ndarray] = None) -> OcrResult:
    t0 = time.monotonic()
    try:
        raw_text, mean_conf = _tesseract_pass(binary_image, config.TESSERACT_PSM_PRIMARY)
        if not raw_text:
            raw_text, mean_conf = _tesseract_pass(binary_image, config.TESSERACT_PSM_FALLBACK)

        route = _parse_route(raw_text)
        elapsed = time.monotonic() - t0

        return OcrResult(raw_text, route, mean_conf, "tesseract", elapsed)
    except pytesseract.pytesseract.TesseractNotFoundError as e:
        # This is the one case where "fall back to Windows OCR" is actually the
        # right call — the binary genuinely isn't at the resolved path.
        logger.warning(
            "Tesseract binary not found at '%s' (%s). Falling back to Windows OCR "
            "with degraded (estimated, non-numeric) confidence. Fix: install "
            "Tesseract-OCR and/or add it to PATH — see check_tesseract.py.",
            config.TESSERACT_CMD, e,
        )
        return _extract_with_winocr(binary_image, raw_frame=raw_frame)
    except Exception as e:
        # Any other failure (bad image array, missing eng.traineddata, a
        # permissions error, etc.) is a real bug, not a "Tesseract isn't
        # installed" situation — log it loudly and with a traceback instead of
        # silently reporting it as the same thing. Still fall back so one bad
        # frame doesn't crash the request, but this must be visible in logs.
        logger.error(
            "Tesseract OCR pass raised an unexpected error (NOT a 'not found' "
            "issue — investigate this): %s: %s",
            type(e).__name__, e, exc_info=True,
        )
        return _extract_with_winocr(binary_image, raw_frame=raw_frame)


_easyocr_reader = None  # lazy-loaded singleton, only if OCR_ENGINE == "easyocr"


def _extract_with_easyocr(binary_image: np.ndarray) -> OcrResult:
    global _easyocr_reader
    t0 = time.monotonic()
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False)

    results = _easyocr_reader.readtext(binary_image, detail=1)
    if not results:
        return OcrResult("", None, 0.0, "easyocr", time.monotonic() - t0)

    raw_text = " ".join(r[1] for r in results)
    mean_conf = 100.0 * sum(r[2] for r in results) / len(results)
    route = _parse_route(raw_text)
    elapsed = time.monotonic() - t0
    return OcrResult(raw_text, route, mean_conf, "easyocr", elapsed)


_NON_ROUTE_WORDS = ("STOP", "KEEP", "DISTANCE", "FEET", "SPEED", "TATA",
                    "LEYLAND", "APSRTC", "BMTC", "DTC")


def _route_tokens(text: str) -> list:
    """Every route-shaped token in `text`, most specific first.

    Strips registration plates and painted bus markings first, so "AP31TE 5522"
    and "KEEP 50 FEET DISTANCE" cannot masquerade as a route.
    """
    if not text:
        return []

    cleaned = re.sub(config.PLATE_REGEX, " ", text.upper())
    cleaned = re.sub(r"\b(" + "|".join(_NON_ROUTE_WORDS) + r")\b", " ", cleaned)

    seen, tokens = set(), []
    for match in _ROUTE_PATTERN.findall(cleaned):
        if match in ("0", "00", "O") or match in seen:
            continue
        seen.add(match)
        tokens.append(match)
    # Longer tokens carry more information ("55K" over "55"), so try them first.
    tokens.sort(key=len, reverse=True)
    return tokens


def _parse_route(raw_text: str) -> Optional[str]:
    """Pull the most plausible route token out of a flat OCR string.

    Used by the engines that return no per-detection geometry. When geometry is
    available, `_select_best_route` makes a far better-informed choice.
    """
    tokens = _route_tokens(raw_text)
    return tokens[0] if tokens else None

