FROM python:3.11-slim AS base

WORKDIR /app

# Install build deps in a separate layer so they don't bloat the final image
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "rival_radar.api:app", "--host", "0.0.0.0", "--port", "8000"]
