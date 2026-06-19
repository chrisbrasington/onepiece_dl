# Build from the repo root: docker build -f services/downloader/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 ONEPIECE_STORAGE=/data

# rsync is used to mirror chapter PDFs to the optional BACKUP_PATH.
RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*

COPY services/downloader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onepiece ./onepiece
COPY services/downloader/main.py .

CMD ["python", "main.py"]
