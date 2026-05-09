FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# librdkafka is bundled in the confluent-kafka manylinux wheel, but we need
# build essentials only if pip falls back to source — slim image keeps minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY collector/requirements.txt /app/collector/requirements.txt
RUN pip install --no-cache-dir -r /app/collector/requirements.txt

COPY collector /app/collector

CMD ["python", "-m", "collector.main"]
