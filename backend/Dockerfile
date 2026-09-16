FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=0 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

# System deps: OCR, PDF rendering, OpenCV/OpenCLIP libs, postgres client, curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    poppler-utils \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first (much smaller than default CUDA wheels).
# If you have a GPU build, comment the next two lines out.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8002/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
