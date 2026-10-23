# Deployment Guide: Vercel Serverless Deployment

This repository supports zero-configuration deployment to **Vercel** as a serverless Python web application using Google Cloud Vision OCR.

---

## Architecture Overview

- **Edge / Local (Raspberry Pi & Desktop)**: Uses an **offline-first** pipeline (`OCR_MODE=auto` or `OCR_MODE=offline`) with RapidOCR (PP-OCRv4) / Tesseract running on device.
- **Cloud / Serverless (Vercel)**: Runs with `OCR_MODE=online` by default. Vercel serverless containers lack `libGL.so.1` and local Tesseract binaries, so the online mode offloads text recognition to **Google Cloud Vision REST API**, requiring only lightweight pure-Python dependencies (`flask`, `requests`, `Pillow`).

---

## Step-by-Step Vercel Deployment

### 1. Obtain a Google Cloud Vision API Key
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a Google Cloud project.
3. In the sidebar, navigate to **APIs & Services > Library** and enable **Cloud Vision API**.
4. Navigate to **APIs & Services > Credentials**.
5. Click **+ CREATE CREDENTIALS > API key**.
6. Copy the generated API key.
   *(Recommended: Under "API restrictions", select "Restrict key" and choose "Cloud Vision API").*

---

### 2. Configure Environment Variables in Vercel
1. Log in to your [Vercel Dashboard](https://vercel.com/dashboard).
2. Open your project (e.g. `bus-route-identifier`).
3. Go to **Settings > Environment Variables**.
4. Add the following variables:
   - **`GOOGLE_VISION_API_KEY`**: Paste your Google Cloud Vision API key.
   - **`OCR_MODE`**: Set to `online` (production, preview, and development).
   - **`ONLINE_TIMEOUT_S`**: (Optional) Set to `3.0`.
5. Click **Save**.

---

### 3. Deploy / Redeploy
1. In your Vercel project, go to the **Deployments** tab.
2. Click the three dots (`...`) on the latest deployment and select **Redeploy** (ensure "Use existing Build Cache" is unchecked so new environment variables take effect).
3. Wait for the deployment build to complete (typically ~10-15 seconds).

---

### 4. Test the Live Deployment
1. Open your live Vercel URL (e.g., `https://your-app.vercel.app/`).
2. **Verify Configuration**:
   - If `GOOGLE_VISION_API_KEY` is configured, the page loads cleanly with no warnings.
   - If the key is missing or unset, an advisory notice appears at the top:
     `⚠️ Online OCR Notice: GOOGLE_VISION_API_KEY environment variable is not configured.`
3. **Test Image Identification**:
   - Drag and drop a bus route signboard photo (e.g., from `test_images/clear_route_12.jpg` or `APSRTC_55K_Bus.jpg`) into the dropzone, or click one of the quick test chips.
   - Verify the identified route number appears large on the destination board (e.g., `12` or `55K`).
   - Check the muted sub-line underneath the route number:
     `Engine: online (XXXms)`
   - Verify the voice announcement speaks the route and destination.

---

## Local Development vs. Production Deployment

| Setting | Local Development / Pi | Vercel Serverless |
| :--- | :--- | :--- |
| **Default `OCR_MODE`** | `auto` (Offline primary, online fallback) | `online` (Google Vision) |
| **Dependencies** | OpenCV, ONNX Runtime, RapidOCR, PyTesseract | Pure Python (`flask`, `requests`, `Pillow`) |
| **Credentials File** | Local `.env` (never committed) | Vercel Environment Variables |
| **Offline Fallback** | Runs local PP-OCRv4 / Tesseract | Disabled (Cloud-native) |
