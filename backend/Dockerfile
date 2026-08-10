FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml requirements.lock ./
COPY poker_coach ./poker_coach

# docker CLI so the solver worker can spawn sidecar containers via the
# mounted docker socket (Linux deployments; Windows dev runs the worker on the host)
RUN pip install --no-cache-dir ".[postgres,redis]" \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uvicorn", "poker_coach.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
