"""
ocr_router.py
=============
Hybrid OCR Router:
  - "offline": Offline engine only (RapidOCR PP-OCRv4 / Tesseract). Zero network calls.
  - "online" : Google Cloud Vision API only.
  - "auto"   : Run offline engine first. If it returns no route or confidence is
               below config.OFFLINE_MIN_CONFIDENCE, fall back to Google Cloud Vision.
               If online also fails, return no-result and use existing "not detected" feedback.

Router return format:
  {
      "route": str | None,
      "engine": "offline" | "online",
      "latency_ms": float,
      "confidence": float,
      "raw_text": str,
      "confidence_is_estimated": bool,
      "ocr_result": OcrResult,
  }
"""
import logging
import time
from typing import Any, Dict, Optional

import config
import ocr_online

logger = logging.getLogger("bus_route.router")


def route_ocr(
    image_input: Any,
    binary_image: Optional[Any] = None,
    mode: Optional[str] = None,
    timeout_s: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Main entry point for hybrid OCR routing.

    Args:
        image_input: Raw image frame (numpy array, bytes, or file path).
        binary_image: Preprocessed binary image for Tesseract (optional).
        mode: "auto" | "offline" | "online" (defaults to config.OCR_MODE).
        timeout_s: Online request timeout in seconds (defaults to config.ONLINE_TIMEOUT_S).

    Returns:
        Dict containing route, engine ("offline" | "online"), latency_ms, etc.
    """
    import ocr_engine

    active_mode = (mode or getattr(config, "OCR_MODE", "auto")).lower().strip()
    timeout = timeout_s if timeout_s is not None else getattr(config, "ONLINE_TIMEOUT_S", 3.0)

    t0 = time.monotonic()

    # --------------------------------------------------------------------------
    # MODE: OFFLINE ONLY
    # --------------------------------------------------------------------------
    if active_mode == "offline":
        logger.debug("Routing to OFFLINE engine only.")
        res = ocr_engine.extract_route_offline(binary_image, raw_frame=image_input)
        latency_ms = (time.monotonic() - t0) * 1000.0
        return {
            "route": res.route,
            "engine": "offline",
            "latency_ms": round(latency_ms, 2),
            "confidence": res.confidence,
            "raw_text": res.raw_text,
            "confidence_is_estimated": res.confidence_is_estimated,
            "ocr_result": res,
        }

    # --------------------------------------------------------------------------
    # MODE: ONLINE ONLY
    # --------------------------------------------------------------------------
    if active_mode == "online":
        logger.debug("Routing to ONLINE engine only (Google Cloud Vision).")
        online_data = ocr_online.detect_route_online_full(image_input, timeout_s=timeout)
        latency_ms = (time.monotonic() - t0) * 1000.0

        route = online_data.get("route")
        confidence = online_data.get("confidence")
        if confidence is None:
            confidence = 95.0 if route else 0.0

        raw_text = online_data.get("raw_text", "")
        ocr_res = ocr_engine.OcrResult(
            raw_text=raw_text,
            route=route,
            confidence=confidence,
            engine="online",
            elapsed_s=latency_ms / 1000.0,
            confidence_is_estimated=False,
        )
        return {
            "route": route,
            "engine": "online",
            "latency_ms": round(latency_ms, 2),
            "confidence": confidence,
            "raw_text": raw_text,
            "confidence_is_estimated": False,
            "ocr_result": ocr_res,
        }

    # --------------------------------------------------------------------------
    # MODE: AUTO (OFFLINE FIRST, ONLINE FALLBACK)
    # --------------------------------------------------------------------------
    # 1. Run offline engine first
    logger.debug("Running AUTO mode: offline engine first...")
    offline_res = ocr_engine.extract_route_offline(binary_image, raw_frame=image_input)
    min_confidence = getattr(config, "OFFLINE_MIN_CONFIDENCE", 45.0)

    # Check if offline produced a valid route with acceptable confidence
    if offline_res.route and offline_res.confidence >= min_confidence:
        latency_ms = (time.monotonic() - t0) * 1000.0
        logger.info(
            "Auto router: Offline engine succeeded (route=%s, conf=%.1f, latency=%.1fms).",
            offline_res.route, offline_res.confidence, latency_ms
        )
        return {
            "route": offline_res.route,
            "engine": "offline",
            "latency_ms": round(latency_ms, 2),
            "confidence": offline_res.confidence,
            "raw_text": offline_res.raw_text,
            "confidence_is_estimated": offline_res.confidence_is_estimated,
            "ocr_result": offline_res,
        }

    # 2. Offline failed or produced low confidence -> call online fallback
    logger.info(
        "Auto router: Offline route=%s, conf=%.1f (threshold=%.1f). Falling back to Google Cloud Vision...",
        offline_res.route, offline_res.confidence, min_confidence
    )

    online_data = ocr_online.detect_route_online_full(image_input, timeout_s=timeout)
    latency_ms = (time.monotonic() - t0) * 1000.0

    if online_data.get("route"):
        route = online_data["route"]
        confidence = online_data.get("confidence") or 95.0
        raw_text = online_data.get("raw_text", "")
        logger.info(
            "Auto router: Online fallback succeeded (route=%s, conf=%.1f, total_latency=%.1fms).",
            route, confidence, latency_ms
        )
        ocr_res = ocr_engine.OcrResult(
            raw_text=raw_text,
            route=route,
            confidence=confidence,
            engine="online",
            elapsed_s=latency_ms / 1000.0,
            confidence_is_estimated=False,
        )
        return {
            "route": route,
            "engine": "online",
            "latency_ms": round(latency_ms, 2),
            "confidence": confidence,
            "raw_text": raw_text,
            "confidence_is_estimated": False,
            "ocr_result": ocr_res,
        }

    # 3. Online also failed: return no-result and use existing "not detected" feedback
    logger.info("Auto router: Online fallback also failed to detect a valid route.")
    combined_raw = online_data.get("raw_text") or offline_res.raw_text
    ocr_res = ocr_engine.OcrResult(
        raw_text=combined_raw,
        route=None,
        confidence=0.0,
        engine="offline",
        elapsed_s=latency_ms / 1000.0,
        confidence_is_estimated=False,
    )
    return {
        "route": None,
        "engine": "offline",
        "latency_ms": round(latency_ms, 2),
        "confidence": 0.0,
        "raw_text": combined_raw,
        "confidence_is_estimated": False,
        "ocr_result": ocr_res,
    }
