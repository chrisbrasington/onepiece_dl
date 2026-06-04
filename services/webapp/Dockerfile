# Build from the repo root: docker build -f services/webapp/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 ONEPIECE_STORAGE=/data WEBAPP_PORT=8080

COPY services/webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onepiece ./onepiece
COPY services/webapp/main.py .
COPY services/webapp/static ./static

EXPOSE 8080
CMD ["python", "main.py"]
