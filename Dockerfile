# CiV backend image: Python 3.14 + uv, run by Gunicorn as a non-root user.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Packages first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# Bake the admin panel's styles into the image. The key here is only for this build step.
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=false python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 civ && chown -R civ /app
USER civ

EXPOSE 8000
ENTRYPOINT ["./deploy/entrypoint.sh"]
