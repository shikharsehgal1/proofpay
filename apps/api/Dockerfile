# Build from repository root:
#   fly deploy -c apps/api/fly.toml --dockerfile apps/api/Dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY demo-bounty /app/demo-bounty
COPY demo-search /app/demo-search
COPY apps/api/pyproject.toml /app/pyproject.toml
COPY apps/api/app /app/app
COPY apps/api/alembic.ini /app/alembic.ini
COPY apps/api/alembic /app/alembic

RUN pip install --no-cache-dir -e . pytest

ENV PYTHONUNBUFFERED=1
ENV WORKSPACES_DIR=/data/workspaces
ENV ARTIFACTS_DIR=/data/artifacts
# Seeds live inside the image on Fly
ENV DEMO_SEARCH_PATH=/app/demo-search
ENV DEMO_BOUNTY_PATH=/app/demo-bounty

RUN mkdir -p /data/workspaces /data/artifacts

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
