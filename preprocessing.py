"""
preprocessing.py
================
OpenCV pipeline: grayscale -> CLAHE -> adaptive binarization.

Every step here is chosen for speed over polish:
  - Grayscale conversion is trivial cost and removes 2/3 of the data
    OCR would otherwise have to look at.
  - CLAHE (adaptive histogram equalization) fixes the uneven lighting
    that's near-guaranteed on a bus route board photographed outdoors
    (glare, shadow from the bus body, low sun angle).
  - Adaptive thresholding (rather than a single global threshold)
    handles boards where lighting varies across the frame — very common
    when the board is lit from one side.

No blurring/denoising step is included by default: it costs milliseconds
for a benefit Tesseract rarely needs on already-high-contrast route
boards. Uncomment `_denoise` below if you see OCR struggling on noisy
low-light frames.
"""
import time
import logging
from typing import Any

import config

logger = logging.getLogger("bus_route.preprocessing")

_cv2 = None
_clahe_obj = None


def _get_cv2_and_clahe():
    global _cv2, _clahe_obj
    if _cv2 is None:
        import cv2 as _c
        _cv2 = _c
        _clahe_obj = _cv2.createCLAHE(
            clipLimit=config.CLAHE_CLIP_LIMIT,
            tileGridSize=config.CLAHE_TILE_GRID_SIZE,
        )
    return _cv2, _clahe_obj


class _LazyClahe:
    def apply(self, gray):
        _, clahe = _get_cv2_and_clahe()
        return clahe.apply(gray)


_clahe = _LazyClahe()



def preprocess(frame: Any) -> Any:
    """
    Run the full pipeline on a raw camera frame and return a binarized
    image ready for OCR.
    """
    t0 = time.monotonic()
    cv2, _ = _get_cv2_and_clahe()

    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY) if frame.ndim == 3 else frame

    if config.UPSCALE_FACTOR != 1.0:
        gray = cv2.resize(
            gray, None,
            fx=config.UPSCALE_FACTOR, fy=config.UPSCALE_FACTOR,
            interpolation=cv2.INTER_LINEAR,
        )

    equalized = _clahe.apply(gray)

    binary = cv2.adaptiveThreshold(
        equalized,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        config.ADAPTIVE_THRESH_BLOCK_SIZE,
        config.ADAPTIVE_THRESH_C,
    )

    elapsed = time.monotonic() - t0
    logger.debug("Preprocess completed in %.3fs", elapsed)
    if elapsed > config.BUDGET_PREPROCESS:
        logger.warning(
            "Preprocess took %.3fs, over the %.3fs budget", elapsed, config.BUDGET_PREPROCESS
        )
    return binary


def _denoise(gray: Any) -> Any:
    """Optional — fastNlMeansDenoising costs ~40-80ms on a Zero 2 W.
    Only enable if field testing shows OCR errors from sensor noise."""
    cv2, _ = _get_cv2_and_clahe()
    return cv2.fastNlMeansDenoising(gray, h=10)
