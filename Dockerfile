# Casa Presente in one container: the Python API/cameras and the Node WhatsApp gateway.
# Build: docker compose build   ·   Run: docker compose up -d   (see README → Docker)

FROM node:22-bookworm-slim AS node
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 PORT=8000 WA_PORT=3001 CAMERA_DATA_DIR=/app/data
# FFmpeg converts recordings; libGL/glib are needed by OpenCV; DejaVu draws the names on video.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
RUN python -m venv .venv
COPY requirements.txt .
RUN .venv/bin/pip install -r requirements.txt
# Official models, verified by SHA-256.
COPY scripts/download_models.py scripts/
RUN .venv/bin/python scripts/download_models.py
COPY --from=node /app/node_modules node_modules
COPY . .

RUN useradd --uid 1000 --create-home casa && mkdir -p data && chown casa:casa data
USER casa
VOLUME /app/data
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s \
  CMD .venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/auth/me', timeout=8)"
CMD ["./start.sh"]
