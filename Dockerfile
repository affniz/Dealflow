# syntax=docker/dockerfile:1
# One image for the whole app: the API, the built React app (served by the API) and the
# background worker. Build from the repository root: docker build -t dealflow .

FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=120 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
# dependencies first, so code changes don't reinstall them
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev
COPY backend/ ./
COPY --from=web /web/dist ./static
ENV ENVIRONMENT=production \
    STATIC_DIR=/app/static \
    PORT=8000
RUN useradd --create-home dealflow && chown dealflow /app
USER dealflow
EXPOSE 8000
CMD ["bash", "scripts/start.sh"]
