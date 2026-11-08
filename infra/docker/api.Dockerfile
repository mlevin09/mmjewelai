FROM python:3.12.14-slim-bookworm AS builder

WORKDIR /build
COPY packages packages
COPY apps/api apps/api
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip wheel --no-cache-dir --wheel-dir /wheels \
      ./packages/domain ./packages/auth ./packages/auth_oidc \
      ./packages/auth_identity_platform ./packages/assets \
      ./packages/assets_gcs ./packages/generation_queue ./packages/generation_queue_gcp \
      ./packages/model_gateway ./packages/parser ./packages/persistence ./packages/prompts \
      ./packages/text_understanding_google \
      ./apps/api

FROM python:3.12.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JEWELAI_REPOSITORY_ROOT=/app
WORKDIR /app
RUN groupadd --gid 10001 jewelai && \
    useradd --uid 10001 --gid jewelai --no-create-home --shell /usr/sbin/nologin jewelai
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY data /app/data
COPY specs /app/specs
COPY packages/persistence/alembic.ini /app/packages/persistence/alembic.ini
COPY packages/persistence/migrations /app/packages/persistence/migrations
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "jewelai_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
