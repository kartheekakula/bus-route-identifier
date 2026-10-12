"""
tools/test_local_pipeline.py
============================
Local PC testing harness: programmatically mocks the camera and OCR engine
to simulate different readouts and verify the correction, lookup, logging,
and feedback routing without requiring Raspberry Pi hardware or Tesseract.
"""
import logging
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import config
import ocr_engine
from camera import MockCamera
from main import BusRouteIdentifier
from ocr_engine import OcrResult

# Set up logging output to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Setup a dummy image for the MockCamera to read
test_images_dir = project_root / "test_images"
test_images_dir.mkdir(exist_ok=True)
dummy_img_path = test_images_dir / "pc_test_frame.jpg"

if not dummy_img_path.exists():
    import numpy as np
    import cv2

    # Write a simple black canvas to represent the frame
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.imwrite(str(dummy_img_path), dummy_frame)

# Variable to dynamic override OCR readout in mock
mock_ocr_readout = "3O5"


def mock_extract_route(binary_image) -> OcrResult:
    """Mock extractor returning the current mock readout value."""
    return OcrResult(
        raw_text=mock_ocr_readout,
        route=mock_ocr_readout,
        confidence=90.0,
        engine="mock_ocr",
        elapsed_s=0.04,
    )


# Override the OCR function with our mock in the main module's imported namespace
import main
main.extract_route = mock_extract_route

# Initialize main orchestrator
print("Initializing BusRouteIdentifier...")
app = BusRouteIdentifier()
app.camera = MockCamera(str(dummy_img_path))
app.camera.start()

# --- RUN MOCK PIPELINE TESTS ---

print("\n==================================================================")
print("TEST 1: Noisy read '3O5' (expected: corrected to '305' -> Railway Station)")
print("==================================================================")
mock_ocr_readout = "3O5"
app.run_once()

print("\n==================================================================")
print("TEST 2: Lowercase read '23a' (expected: corrected to uppercase '23A' -> Ganguru)")
print("==================================================================")
mock_ocr_readout = "23a"
app.run_once()

print("\n==================================================================")
print("TEST 3: Close matches '23k' (expected: corrected to '23K' -> Kesaraneni)")
print("==================================================================")
mock_ocr_readout = "23k"
app.run_once()

print("\n==================================================================")
print("TEST 4: Unrecognized route '999' (expected: no correction -> plain fallback)")
print("==================================================================")
mock_ocr_readout = "999"
app.run_once()

print("\n==================================================================")
print("TEST 5: No route detected (expected: error feedback)")
print("==================================================================")
mock_ocr_readout = None
app.run_once()

app.camera.stop()
print("\nLocal testing complete.")
