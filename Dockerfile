FROM node:24-bookworm-slim AS web-assets

WORKDIR /build
RUN corepack enable
COPY web-assets/package.json web-assets/pnpm-lock.yaml web-assets/pnpm-workspace.yaml ./web-assets/
WORKDIR /build/web-assets
RUN corepack pnpm install --frozen-lockfile
WORKDIR /build
COPY web-assets ./web-assets
COPY app/web/templates ./app/web/templates
RUN cd web-assets && corepack pnpm build

FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic ./alembic
COPY alembic.ini ./
COPY app ./app
COPY evaluation/datasets ./evaluation/datasets
COPY evaluation/reports ./evaluation/reports
COPY --from=web-assets /build/app/web/static ./app/web/static
RUN mkdir -p /app/data /app/logs /app/evaluation/local-reviewed /app/evaluation/local-reviewed/reports
