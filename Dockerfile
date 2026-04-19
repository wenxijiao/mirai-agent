# Mirai HTTP server (core API). Mount a volume for ~/.mirai to persist config and memory.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    MIRAI_LOG_LEVEL=INFO

COPY pyproject.toml MANIFEST.in README.md LICENSE NOTICE ./
COPY mirai ./mirai

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "mirai.core.api"]
