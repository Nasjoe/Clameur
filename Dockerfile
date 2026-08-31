FROM python:3.13-slim

# ffmpeg est une dependance de l'image, pas du poste du mainteneur.
# / ffmpeg belongs to the image, not to the maintainer's machine.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1
# Les binaires du venv dans le PATH : supervisord appelle `gunicorn` et
# `celery` DIRECTEMENT, jamais via `uv run` — un wrapper `uv` intercepterait
# le SIGTERM destine au worker. Voir supervisord.conf.
# / venv binaries on PATH: supervisord must call them directly, not via uv run.
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

# Les fichiers statiques sont rassembles au build : nginx les sert depuis le
# volume, sans que Django ait a s'en occuper au demarrage.
# / Static files are collected at build time; nginx serves them from the volume.
RUN SECRET_KEY=build-uniquement DEBUG=false \
    python manage.py collectstatic --noinput --clear
