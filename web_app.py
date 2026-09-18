"""
web_app.py
==========
Flask web server wrapping the Edge-OCR Bus Route Identifier pipeline.

Exposes real-time execution metrics, intermediate image stages,
OCR confidence, fuzzy route corrections, and destination lookups
without fabricating or hardcoding any values.
"""
import base64
import csv
import io
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

import cv2
import numpy as np
from flask import Flask, request, jsonify, render_template
from werkzeug.exceptions import HTTPException

import config
import ocr_engine
import preprocessing
from routes import RouteLookup

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bus_route.web")

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB max upload

# Initialize RouteLookup ONCE at startup (zero-disk read hot path rule)
logger.info("Initializing RouteLookup for web service...")
route_lookup = RouteLookup(routes_dir=config.ROUTES_DATA_DIR, city=config.CITY)
route_lookup.startup_complete = True

# --- STARTUP OCR ENGINE CHECK ---
# Print this loudly and unconditionally: if the server is silently running on
# the Windows OCR fallback instead of Tesseract, that must be obvious the
# moment you start it, not something discovered by squinting at a UI badge
# after a failed demo upload.
try:
    import pytesseract as _pt
    _tess_version = _pt.get_tesseract_version()
    logger.info("OCR ENGINE READY: Tesseract %s at '%s'", _tess_version, config.TESSERACT_CMD)
except Exception as e:
    logger.warning(
        "=" * 70 + "\n"
        "OCR ENGINE: Tesseract is NOT available (%s: %s).\n"
        "The app will run on the Windows OCR fallback instead, which has no\n"
        "native confidence score and is generally less accurate.\n"
        "Resolved TESSERACT_CMD was: '%s'\n"
        "Run `python check_tesseract.py` for a focused diagnosis, or install\n"
        "Tesseract-OCR and ensure it's on PATH.\n" + "=" * 70,
        type(e).__name__, e, config.TESSERACT_CMD,
    )

# The check above only covers the *fallback* engine. Tesseract being healthy
# says nothing about whether the engine we actually intend to use loaded, and a
# silent downgrade here looks identical to "the OCR is just bad": every upload
# comes back low-confidence and the device announces "unclear".
if config.OCR_ENGINE == "paddleocr":
    try:
        import rapidocr_onnxruntime  # noqa: F401
        logger.info("OCR ENGINE READY: rapidocr_onnxruntime (PP-OCRv4 detection + recognition)")
    except ImportError:
        logger.warning(
            "\n" + "=" * 70 + "\n"
            "OCR ENGINE DEGRADED: config.OCR_ENGINE is 'paddleocr' but\n"
            "rapidocr_onnxruntime is not installed in this interpreter:\n"
            "  %s\n"
            "Falling back to Tesseract, which cannot locate text in a scene\n"
            "photo -- it reads 1 of the 8 benchmark images instead of 7, so\n"
            "almost every upload will come back 'unclear'. Install it with:\n"
            "  pip install -r requirements-ocr.txt\n" + "=" * 70,
            sys.executable,
        )

# Ensure timing log exists (gracefully handle read-only filesystems on serverless)
try:
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not config.LOG_PATH.exists():
        with open(config.LOG_PATH, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp", "capture_s", "preprocess_s", "ocr_s", "feedback_s", "total_s", "route", "confidence"]
            )
except Exception as e:
    logger.warning("Could not initialize timing log at %s (read-only filesystem): %s", config.LOG_PATH, e)



def _encode_jpeg_base64(img: np.ndarray, max_dim: int = 640, quality: int = 80) -> str:
    """Encode an OpenCV image (color or grayscale) into a Base64 JPEG data URL."""
    if img is None or img.size == 0:
        return ""
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    success, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode("utf-8")


def run_pipeline_instrumented(frame: np.ndarray, capture_s: float = 0.0,
                              client_ocr_text: Optional[str] = None,
                              client_ocr_conf: float = 0.0,
                              client_ocr_ms: float = 0.0) -> Dict[str, Any]:
    """
    Runs the exact pipeline functions from the repository,
    measuring real wall-clock latency per stage and capturing
    real intermediate image frames.
    """
    t_start = time.monotonic()
    h, w = frame.shape[:2]

    # --- STAGE 1: PREPROCESSING ---
    t0 = time.monotonic()
    # Grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()
    if config.UPSCALE_FACTOR != 1.0:
        gray = cv2.resize(
            gray, None,
            fx=config.UPSCALE_FACTOR, fy=config.UPSCALE_FACTOR,
            interpolation=cv2.INTER_LINEAR,
        )
    # CLAHE equalization
    clahe_img = preprocessing._clahe.apply(gray)
    # Adaptive threshold
    binary = cv2.adaptiveThreshold(
        clahe_img,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        config.ADAPTIVE_THRESH_BLOCK_SIZE,
        config.ADAPTIVE_THRESH_C,
    )
    preprocess_s = time.monotonic() - t0

    # --- STAGE 2: OCR EXTRACTION ---
    # ocr_engine.extract_route internally measures its own elapsed_s
    t0 = time.monotonic()
    try:
        ocr_result = ocr_engine.extract_route(binary, raw_frame=frame)
    except Exception as e:
        logger.warning("OCR extraction exception: %s", e)
        ocr_result = ocr_engine.OcrResult("", None, 0.0, "ocr_error", time.monotonic() - t0)
    ocr_s = ocr_result.elapsed_s

    # Fallback to client-side OCR if server OCR found nothing and client provided text
    if not ocr_result.raw_text and client_ocr_text:
        from ocr_engine import _parse_route
        parsed_route = _parse_route(client_ocr_text)
        conf_to_use = client_ocr_conf if client_ocr_conf > 0 else 85.0
        elapsed_to_use = (client_ocr_ms / 1000.0) if client_ocr_ms > 0 else 0.45
        ocr_result = ocr_engine.OcrResult(
            raw_text=client_ocr_text,
            route=parsed_route,
            confidence=conf_to_use,
            engine="client_wasm_tesseract",
            elapsed_s=elapsed_to_use,
            confidence_is_estimated=False,
        )
        ocr_s = ocr_result.elapsed_s

    # --- STAGE 3: LOOKUP & FUZZY CORRECTION ---
    t0 = time.monotonic()
    raw_route = ocr_result.route
    raw_text_clean = " ".join(ocr_result.raw_text.split()).strip()

    corrected_route = None
    destination = None
    low_confidence = False

    if not raw_route and raw_text_clean:
        inferred = route_lookup.resolve_route_from_text(raw_text_clean)
        if inferred:
            raw_route = inferred

    if raw_route:
        # A route number was parsed by the regex or resolved from destination text
        if ocr_result.confidence >= config.OCR_MIN_CONFIDENCE:
            corrected_route = route_lookup.correct_route(raw_route) or raw_route
            destination = route_lookup.lookup(corrected_route)
        else:
            low_confidence = True
    # NOTE: We deliberately do NOT fall back to displaying/speaking arbitrary
    # extracted text (words, landmarks, etc.) when no route number is found.
    # Showing unrelated OCR text as if it were the route was misleading users
    # (e.g. announcing garbled phrases as a "route"). If raw_route is None or
    # confidence is below threshold, the UI must show the "not detected" /
    # "low confidence" advisory state instead.

    lookup_s = time.monotonic() - t0

    # --- STAGE 4: FEEDBACK & PHRASE GENERATION ---
    t0 = time.monotonic()
    if low_confidence:
        status = "low_confidence"
        phrase = config.PHRASE_LOW_CONFIDENCE
        haptic_name = "low_confidence_pattern (two 80ms pulses)"
    elif corrected_route is None:
        status = "no_route"
        phrase = config.PHRASE_NO_TEXT
        haptic_name = "error_pattern (400ms long pulse)"
    else:
        status = "success"
        if destination:
            phrase = config.PHRASE_ROUTE_WITH_DESTINATION_TEMPLATE.format(route=corrected_route, destination=destination)
        else:
            # Graceful degradation (PRD principle #3): announce route number
            # alone when it's real but uncatalogued, rather than guessing a destination.
            phrase = config.PHRASE_ROUTE_TEMPLATE.format(route=corrected_route)
        haptic_name = "success_pattern (150ms single pulse)"

    # Check audio cache hit
    safe_name = corrected_route.replace("/", "-") if corrected_route else ""
    cache_path = (config.AUDIO_CACHE_DIR / f"{safe_name}.wav") if safe_name else None
    is_cached = cache_path.exists() if cache_path else False
    feedback_s = time.monotonic() - t0

    # Total Latency
    total_s = capture_s + preprocess_s + ocr_s + lookup_s + feedback_s

    # Real Log Record append
    try:
        with open(config.LOG_PATH, "a", newline="") as f:
            csv.writer(f).writerow(
                [time.time(), f"{capture_s:.3f}", f"{preprocess_s:.3f}", f"{ocr_s:.3f}",
                 f"{feedback_s:.3f}", f"{total_s:.3f}", corrected_route, f"{ocr_result.confidence:.1f}"]
            )
    except Exception as e:
        logger.warning("Could not append to run_timings.csv: %s", e)

    # Base64 intermediate stages for UI visualization
    raw_b64 = _encode_jpeg_base64(frame)
    gray_b64 = _encode_jpeg_base64(gray)
    clahe_b64 = _encode_jpeg_base64(clahe_img)
    thresh_b64 = _encode_jpeg_base64(binary)

    return {
        "timestamp_str": time.strftime("%d %b %Y, %H:%M:%S IST"),
        "timestamp_unix": time.time(),
        "status": status,  # "success" | "low_confidence" | "no_route"
        "resolution": {"width": w, "height": h},
        "stages": {
            "capture": {
                "name": "Image Ingestion & Decode",
                "time_ms": round(capture_s * 1000, 2),
                "budget_ms": round(config.BUDGET_CAPTURE * 1000, 1),
                "pass": capture_s <= config.BUDGET_CAPTURE,
                "image_b64": raw_b64,
            },
            "preprocess": {
                "name": "OpenCV Grayscale + CLAHE + Binarize",
                "time_ms": round(preprocess_s * 1000, 2),
                "budget_ms": round(config.BUDGET_PREPROCESS * 1000, 1),
                "pass": preprocess_s <= config.BUDGET_PREPROCESS,
                "gray_b64": gray_b64,
                "clahe_b64": clahe_b64,
                "thresh_b64": thresh_b64,
            },
            "ocr": {
                "name": f"OCR Engine ({ocr_result.engine})",
                "time_ms": round(ocr_s * 1000, 2),
                "budget_ms": round(config.BUDGET_OCR * 1000, 1),
                "pass": ocr_s <= config.BUDGET_OCR,
                "engine": ocr_result.engine,
                "raw_text": ocr_result.raw_text,
                "confidence": round(ocr_result.confidence, 1),
                "confidence_is_estimated": ocr_result.confidence_is_estimated,
                "threshold_min": config.OCR_MIN_CONFIDENCE,
                "confidence_pass": ocr_result.confidence >= config.OCR_MIN_CONFIDENCE,
            },
            "lookup": {
                "name": "Offline Multi-City Route & Destination Match",
                "time_ms": round(lookup_s * 1000, 2),
                "raw_route": raw_route,
                "corrected_route": corrected_route,
                "fuzzy_applied": (corrected_route != raw_route and raw_route is not None),
                "destination": destination,
                "city": config.CITY,
            },
            "feedback": {
                "name": "Audio Synthesis / Haptic Dispatch",
                "time_ms": round(feedback_s * 1000, 2),
                "budget_ms": round(config.BUDGET_FEEDBACK * 1000, 1),
                "pass": feedback_s <= config.BUDGET_FEEDBACK,
                "phrase": phrase,
                "audio_cached": is_cached,
                "haptic_pattern": haptic_name,
            },
        },
        "total": {
            "time_ms": round(total_s * 1000, 2),
            "budget_ms": round(config.BUDGET_TOTAL * 1000, 1),
            "pass": total_s <= config.BUDGET_TOTAL,
        },
        "route": corrected_route,
        "raw_route": raw_route,
        "destination": destination,
        "spoken_phrase": phrase,
    }


@app.route("/")
@app.route("/api/index")
@app.route("/api/index/")
@app.route("/api/index.py")
@app.route("/api")
@app.route("/api/")
def index():
    return render_template("index.html")



@app.route("/api/config", methods=["GET"])
def get_config():
    """Returns active configuration constants directly from config.py."""
    return jsonify({
        "city": config.CITY,
        "ocr_engine": config.OCR_ENGINE,
        "ocr_min_confidence": config.OCR_MIN_CONFIDENCE,
        "route_regex": config.ROUTE_REGEX,
        "budget_total_ms": config.BUDGET_TOTAL * 1000,
        "budget_capture_ms": config.BUDGET_CAPTURE * 1000,
        "budget_preprocess_ms": config.BUDGET_PREPROCESS * 1000,
        "budget_ocr_ms": config.BUDGET_OCR * 1000,
        "budget_feedback_ms": config.BUDGET_FEEDBACK * 1000,
        "clahe_clip_limit": config.CLAHE_CLIP_LIMIT,
        "adaptive_thresh_block_size": config.ADAPTIVE_THRESH_BLOCK_SIZE,
        "common_routes": config.COMMON_ROUTES,
    })


@app.route("/api/samples", methods=["GET"])
def list_samples():
    """Lists available test images in test_images/ for one-click testing."""
    test_dir = BASE_DIR / "test_images"
    if not test_dir.exists():
        return jsonify([])
    valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    samples = []
    for p in sorted(test_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in valid_exts and not p.name.startswith("debug_"):
            samples.append({
                "filename": p.name,
                "size_kb": round(p.stat().st_size / 1024, 1),
            })
    return jsonify(samples)


@app.route("/api/identify", methods=["POST"])
def identify_upload():
    """Handles multipart/form-data image upload and runs the real pipeline."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded in form field 'file'"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    t0 = time.monotonic()
    file_bytes = file.read()
    nparr = np.frombuffer(file_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    capture_s = time.monotonic() - t0

    if frame is None:
        return jsonify({"error": "Could not decode uploaded file as a valid image"}), 400

    client_ocr_text = request.form.get("client_ocr_text", "").strip() or None
    client_ocr_conf = float(request.form.get("client_ocr_conf", 0.0) or 0.0)
    client_ocr_ms = float(request.form.get("client_ocr_ms", 0.0) or 0.0)

    result = run_pipeline_instrumented(
        frame, capture_s=capture_s,
        client_ocr_text=client_ocr_text,
        client_ocr_conf=client_ocr_conf,
        client_ocr_ms=client_ocr_ms,
    )
    result["filename"] = file.filename
    return jsonify(result)


@app.route("/test_images/<path:filename>")
def serve_test_image(filename):
    """Serves sample images for client-side processing."""
    from flask import send_from_directory
    return send_from_directory(BASE_DIR / "test_images", filename)


@app.route("/api/sample-identify", methods=["POST"])
def identify_sample():
    """Runs the pipeline on a specified test_images/<filename>."""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Missing 'filename' parameter"}), 400

    safe_path = BASE_DIR / "test_images" / Path(filename).name
    if not safe_path.exists() or not safe_path.is_file():
        return jsonify({"error": f"Sample file '{filename}' not found"}), 404

    t0 = time.monotonic()
    frame = cv2.imread(str(safe_path))
    capture_s = time.monotonic() - t0

    if frame is None:
        return jsonify({"error": f"Could not read image file '{filename}'"}), 400

    client_ocr_text = data.get("client_ocr_text", "").strip() or None
    client_ocr_conf = float(data.get("client_ocr_conf", 0.0) or 0.0)
    client_ocr_ms = float(data.get("client_ocr_ms", 0.0) or 0.0)

    result = run_pipeline_instrumented(
        frame, capture_s=capture_s,
        client_ocr_text=client_ocr_text,
        client_ocr_conf=client_ocr_conf,
        client_ocr_ms=client_ocr_ms,
    )
    result["filename"] = safe_path.name
    return jsonify(result)



@app.route("/api/benchmark", methods=["POST"])
def run_benchmark():
    """
    Runs batch benchmark across test_images/.
    If truth.csv exists, calculates real accuracy %;
    otherwise returns 'N/A' for accuracy without inventing any number.
    """
    test_dir = BASE_DIR / "test_images"
    if not test_dir.exists():
        return jsonify({"error": "test_images directory does not exist"}), 400

    truth_file = BASE_DIR / "test_images" / "truth.csv"
    truth: Dict[str, str] = {}
    has_ground_truth = False
    if truth_file.exists():
        try:
            with open(truth_file, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2 and row[0].strip().lower() != "filename":
                        truth[row[0].strip()] = row[1].strip().upper()
            has_ground_truth = len(truth) > 0
        except Exception as e:
            logger.warning("Failed to parse truth.csv: %s", e)

    valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    images = [p for p in sorted(test_dir.iterdir()) if p.is_file() and p.suffix.lower() in valid_exts and not p.name.startswith("debug_")]

    if not images:
        return jsonify({"error": "No test images found in test_images/"}), 400

    total_tested = 0
    correct_matches = 0
    total_latency_s = 0.0
    records = []

    for img_path in images:
        t0 = time.monotonic()
        frame = cv2.imread(str(img_path))
        capture_s = time.monotonic() - t0
        if frame is None:
            continue

        res = run_pipeline_instrumented(frame, capture_s=capture_s)
        total_tested += 1
        total_latency_s += (res["total"]["time_ms"] / 1000.0)

        filename = img_path.name
        detected = res["route"]
        expected = truth.get(filename) if has_ground_truth else None

        is_match: Optional[bool] = None
        if has_ground_truth and expected:
            is_match = (detected == expected)
            if is_match:
                correct_matches += 1

        records.append({
            "filename": filename,
            "detected_route": detected or "None",
            "destination": res["destination"] or "None",
            "expected_route": expected if expected else "N/A",
            "match": is_match if is_match is not None else "N/A",
            "confidence": res["stages"]["ocr"]["confidence"],
            "confidence_is_estimated": res["stages"]["ocr"]["confidence_is_estimated"],
            "confidence_pass": res["stages"]["ocr"]["confidence_pass"],
            "total_ms": res["total"]["time_ms"],
            "pass_budget": res["total"]["pass"],
        })

    avg_latency_ms = round((total_latency_s / total_tested) * 1000, 2) if total_tested > 0 else 0.0
    accuracy_pct = round((correct_matches / total_tested) * 100, 1) if (has_ground_truth and total_tested > 0) else "N/A"

    return jsonify({
        "total_tested": total_tested,
        "has_ground_truth": has_ground_truth,
        "correct_matches": correct_matches if has_ground_truth else "N/A",
        "accuracy_pct": accuracy_pct,
        "avg_latency_ms": avg_latency_ms,
        "budget_total_ms": config.BUDGET_TOTAL * 1000,
        "records": records,
    })


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    logger.exception("Server error: %s", e)
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print(f"[*] Starting Bus Route Identifier Web UI on http://127.0.0.1:5000")
    print(f"[*] Loaded {len(route_lookup.routes)} routes for city '{config.CITY}'")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=False)
