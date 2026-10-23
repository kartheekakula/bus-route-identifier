"""
ocr_online.py
=============
Online OCR fallback using Google Cloud Vision REST API.
Designed for low memory footprint on edge devices (Raspberry Pi) and
zero-C-dependency execution on serverless runtimes (Vercel).

Credentials are read strictly from environment variables:
  - GOOGLE_VISION_API_KEY (Recommended: API key for Cloud Vision REST endpoint)
  - GOOGLE_APPLICATION_CREDENTIALS (Optional: path to service-account JSON)
"""
import base64
import io
import json
import logging
import os
import time
from typing import Optional, Tuple, Any, Dict, List

import config

logger = logging.getLogger("bus_route.ocr_online")

_VISION_API_URL = "https://vision.googleapis.com/v1/images:annotate"


def _get_api_key() -> Optional[str]:
    """Retrieve Google Vision or Gemini API key from environment."""
    key = os.environ.get("GOOGLE_VISION_API_KEY", "").strip()
    if not key:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
    return key if key else None


def _to_image_bytes(image_input: Any) -> Optional[bytes]:
    """
    Convert various image formats (numpy array, PIL image, bytes, file path)
    into JPEG image bytes without requiring OpenCV if bytes are already provided.
    """
    if image_input is None:
        return None

    if isinstance(image_input, (bytes, bytearray)):
        return bytes(image_input)

    if isinstance(image_input, (str, os.PathLike)):
        try:
            with open(image_input, "rb") as fh:
                return fh.read()
        except Exception as e:
            logger.warning("Failed to read image file '%s': %s", image_input, e)
            return None

    # If it is a PIL Image
    try:
        from PIL import Image
        if isinstance(image_input, Image.Image):
            buf = io.BytesIO()
            image_input.convert("RGB").save(buf, format="JPEG", quality=85)
            return buf.getvalue()
    except ImportError:
        pass

    # If it is a NumPy array (cv2 BGR format)
    if hasattr(image_input, "shape") and hasattr(image_input, "dtype"):
        # Try OpenCV encoding first if available
        try:
            import cv2
            success, buf = cv2.imencode(".jpg", image_input, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if success:
                return buf.tobytes()
        except ImportError:
            pass

        # Fallback to PIL encoding from numpy
        try:
            from PIL import Image
            # image_input is BGR in cv2, convert to RGB for PIL
            if len(image_input.shape) == 3 and image_input.shape[2] == 3:
                rgb_arr = image_input[:, :, ::-1]
            else:
                rgb_arr = image_input
            pil_img = Image.fromarray(rgb_arr)
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception as e:
            logger.warning("Could not convert numpy array to image bytes via PIL: %s", e)

    return None


def _call_google_vision_rest(image_bytes: bytes, api_key: str, timeout_s: float) -> Tuple[Optional[str], List[Any]]:
    """
    Execute POST request against Google Cloud Vision text detection REST endpoint.
    Returns (raw_text, detections_list).
    """
    import requests

    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "requests": [
            {
                "image": {"content": b64_img},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }

    url = f"{_VISION_API_URL}?key={api_key}"
    resp = requests.post(url, json=payload, timeout=timeout_s)
    
    if resp.status_code != 200:
        logger.warning(
            "Google Cloud Vision API HTTP error %d: %s",
            resp.status_code,
            resp.text[:250],
        )
        return None, []

    data = resp.json()
    responses = data.get("responses", [])
    if not responses:
        return "", []

    first_res = responses[0]
    if "error" in first_res:
        err = first_res["error"]
        logger.warning("Google Cloud Vision API error in response: %s", err.get("message", err))
        return None, []

    text_annotations = first_res.get("textAnnotations", [])
    if not text_annotations:
        return "", []

    # First annotation contains the entire transcribed text
    raw_text = text_annotations[0].get("description", "").strip()

    # Individual word/token annotations with bounding polygons
    detections = []
    for ann in text_annotations[1:]:
        word = ann.get("description", "").strip()
        if not word:
            continue
        poly = ann.get("boundingPoly", {}).get("vertices", [])
        box = [(v.get("x", 0), v.get("y", 0)) for v in poly] if poly else []
        conf = float(ann.get("confidence", 0.95))
        detections.append((word, conf, box))

    return raw_text, detections


def _call_gemini_vision_fallback(image_bytes: bytes, api_key: str, timeout_s: float) -> Optional[str]:
    """
    Fallback using Google Gemini generateContent REST API if Vision API returns
    SERVICE_DISABLED or user supplied a Google AI Studio key.
    """
    import requests

    prompt = (
        "You are an OCR engine specialised in reading bus signboards. "
        "Carefully examine this image and extract ALL visible text exactly as it appears. "
        "Return ONLY the raw extracted text - each distinct line of text on its own line. "
        "Do not add explanations, punctuation corrections, or any commentary. "
        "Preserve capitalisation, numbers, and special characters exactly as seen."
    )

    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_img,
                        }
                    },
                ]
            }
        ]
    }

    # Try gemini-2.5-flash or gemini-2.0-flash or gemini-1.5-flash
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=timeout_s)
            if resp.status_code == 200:
                data = resp.json()
                cands = data.get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "").strip()
                        return text
            else:
                logger.debug("Gemini %s responded with status %d", model, resp.status_code)
        except Exception as e:
            logger.debug("Gemini %s request failed: %s", model, e)

    return None


def detect_route_online_full(
    image_bgr: Any, timeout_s: float = 3.0
) -> Dict[str, Any]:
    """
    Comprehensive online detection returning route, confidence, raw text, and latency.
    Never raises an unhandled exception.
    """
    t0 = time.monotonic()
    api_key = _get_api_key()

    if not api_key:
        logger.warning(
            "Online OCR skipped: No GOOGLE_VISION_API_KEY configured in environment or .env."
        )
        return {
            "route": None,
            "confidence": None,
            "raw_text": "",
            "engine": "online",
            "elapsed_s": time.monotonic() - t0,
            "error": "missing_credentials",
        }

    image_bytes = _to_image_bytes(image_bgr)
    if not image_bytes:
        logger.warning("Online OCR failed: Could not convert input image to bytes.")
        return {
            "route": None,
            "confidence": None,
            "raw_text": "",
            "engine": "online",
            "elapsed_s": time.monotonic() - t0,
            "error": "invalid_image",
        }

    # Lazy import parser helpers from ocr_engine to guarantee identical formatting
    from ocr_engine import _parse_route, _select_best_route

    raw_text: Optional[str] = None
    detections: List[Any] = []

    try:
        raw_text, detections = _call_google_vision_rest(image_bytes, api_key, timeout_s=timeout_s)
    except Exception as exc:
        logger.warning("Google Cloud Vision REST request failed: %s", exc)

    # If Vision API call failed (e.g. 403 / service not enabled), attempt Gemini fallback
    if raw_text is None:
        try:
            raw_text = _call_gemini_vision_fallback(image_bytes, api_key, timeout_s=timeout_s)
        except Exception as exc:
            logger.warning("Gemini vision fallback failed: %s", exc)

    if not raw_text:
        return {
            "route": None,
            "confidence": 0.0,
            "raw_text": "",
            "engine": "online",
            "elapsed_s": time.monotonic() - t0,
            "error": "no_text_detected",
        }

    # Parse route number using the exact same logic as offline engine
    route: Optional[str] = None
    confidence: float = 0.0

    # If we got bounding boxes from Google Vision, use geometry-aware route selection
    if detections:
        try:
            frame_height = 1000
            if hasattr(image_bgr, "shape") and len(image_bgr.shape) >= 2:
                frame_height = image_bgr.shape[0]
            r_best, c_best = _select_best_route(detections, frame_height)
            if r_best:
                route, confidence = r_best, c_best
        except Exception as e:
            logger.debug("Geometry selection in online OCR failed: %s", e)

    # Fallback to linear text regex parsing if geometry didn't produce a route
    if not route:
        route = _parse_route(raw_text)
        confidence = 95.0 if route else 0.0

    elapsed = time.monotonic() - t0
    logger.info("Online Google Vision OCR: route=%s, conf=%.1f, elapsed=%.3fs", route, confidence, elapsed)

    return {
        "route": route,
        "confidence": confidence,
        "raw_text": raw_text,
        "engine": "online",
        "elapsed_s": elapsed,
        "error": None,
    }


def detect_route_online(
    image_bgr: Any, timeout_s: float = 3.0
) -> Tuple[Optional[str], Optional[float]]:
    """
    Public API contract required by Step 3:
    detect_route_online(image_bgr, timeout_s=3.0) -> (route: str|None, confidence: float|None)

    Must never raise: on network error, timeout, missing credentials, or API error,
    logs the reason and returns (None, None).
    """
    try:
        res = detect_route_online_full(image_bgr, timeout_s=timeout_s)
        route = res.get("route")
        conf = res.get("confidence")
        if route is None:
            return None, None
        return route, conf
    except Exception as e:
        logger.warning("Unhandled exception in detect_route_online: %s", e, exc_info=True)
        return None, None
