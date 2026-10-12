# Dockerfile for DrishtiCap / Bus Route Identifier Web Service
# Compatible with Hugging Face Spaces (Port 7860, 16GB RAM) and Cloud Containers
FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=7860 \
    OCR_ENGINE=paddleocr

WORKDIR /app

# Install native OS dependencies: Tesseract OCR with English model and OpenCV runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    espeak-ng \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set up non-root user with UID 1000 for Hugging Face Spaces compliance
RUN useradd -m -u 1000 user
RUN mkdir -p /app/logs /app/sounds/cache /home/user/.cache && chown -R 1000:1000 /app /home/user

# Copy the rest of the application code
COPY . .
RUN chown -R 1000:1000 /app

USER 1000

# Expose default Hugging Face Spaces port
EXPOSE 7860

# Start production WSGI server with Gunicorn (2 workers, 4 threads)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-7860} --workers 2 --threads 4 --timeout 120 web_app:app"]
