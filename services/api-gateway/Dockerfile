FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/shared/ ./shared/
COPY services/api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api-gateway/main.py .

CMD ["python", "main.py"]
