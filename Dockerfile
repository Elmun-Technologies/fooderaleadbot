# FOODERA EXPO 2026 lead bot - container image.
#
# The bot is a worker: it talks to Telegram with long polling, so the image exposes
# nothing. Runtime configuration comes from the environment (fly secrets / .env),
# never from a file baked into the image.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# tzdata is not optional here: DISPLAY_TIMEZONE (Asia/Tashkent on the cards, the
# operational day in /stats) is resolved through zoneinfo, and without the database the
# settings layer quietly falls back to UTC.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first: this layer only rebuilds when requirements.txt changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Unprivileged user; /data is the only writable path (used by the optional SQLite mount).
RUN addgroup --system foodera \
    && adduser --system --ingroup foodera --home /app --no-create-home --disabled-password foodera \
    && mkdir -p /data \
    && chown -R foodera:foodera /app /data

USER foodera

# `fly deploy` runs this before starting the bot; locally: docker run --rm image alembic upgrade head
CMD ["python", "-m", "app.main"]
