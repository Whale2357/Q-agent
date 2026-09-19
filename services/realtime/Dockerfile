# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Silero still needs torch/torchaudio, but API-mode servers do not need CUDA wheels.
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
  && pip install --no-cache-dir . \
  && pip check

ENV REALTIME_HOST=0.0.0.0 \
    REALTIME_PORT=8765 \
    REALTIME_DB_PATH=/app/data/q-agent.db \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/data
EXPOSE 8765

CMD ["q-agent-realtime-server"]
