FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml requirements.lock ./
COPY poker_coach ./poker_coach

# docker CLI so the solver worker can spawn sidecar containers via the
# mounted docker socket (Linux deployments; Windows dev runs the worker on the host).
# Debian's docker.io package ships no client binary since the trixie split,
# so fetch the official static CLI instead.
RUN pip install --no-cache-dir ".[postgres,redis]" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz" -o /tmp/docker-cli.tgz \
    && tar -xzf /tmp/docker-cli.tgz -C /tmp \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && apt-get purge -y curl \
    && rm -rf /tmp/docker /tmp/docker-cli.tgz /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uvicorn", "poker_coach.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
