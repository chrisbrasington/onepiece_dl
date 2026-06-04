# Build from the repo root: docker build -f services/bot/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 ONEPIECE_STORAGE=/data

COPY services/bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onepiece ./onepiece
COPY services/bot/main.py .

CMD ["python", "main.py"]
