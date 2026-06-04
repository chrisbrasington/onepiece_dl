# Build from the repo root: docker build -f services/downloader/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 ONEPIECE_STORAGE=/data

COPY services/downloader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onepiece ./onepiece
COPY services/downloader/main.py .

CMD ["python", "main.py"]
