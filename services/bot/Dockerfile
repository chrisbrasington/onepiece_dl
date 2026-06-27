# Build from the repo root: docker build -f services/bot/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 ONEPIECE_STORAGE=/data

# rsync mirrors chapter CBZs to the optional BACKUP_PATH when a download is
# triggered from Discord (same as the downloader does after its own passes).
RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*

COPY services/bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onepiece ./onepiece
COPY services/bot/main.py .

CMD ["python", "main.py"]
