# Build from the repo root: docker build -f services/calibre/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 ONEPIECE_STORAGE=/data

COPY services/calibre/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onepiece ./onepiece
COPY services/calibre/main.py services/calibre/client.py ./

CMD ["python", "main.py"]
