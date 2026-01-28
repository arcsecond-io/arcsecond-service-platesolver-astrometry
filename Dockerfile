FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASTROMETRY_CACHE_DIR=/data/astrometry

# Build deps (kept generic; prune once you confirm what astrometry needs)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      git \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv (optional but convenient)
RUN pip install --no-cache-dir uv

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock /app/uv.lock

# Install deps
RUN uv pip install --system -r pyproject.toml

COPY src/ /app/src/

# Install plate solver service
RUN uv pip install --system .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASTROMETRY_CACHE_DIR=/data/astrometry

WORKDIR /app

# Copy only runtime artifacts from the builder.
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src /app/src

EXPOSE 8900

CMD ["python", "-m", "arcsecond_service_platesolver.main"]
