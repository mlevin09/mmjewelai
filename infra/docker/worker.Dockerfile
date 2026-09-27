FROM python:3.12.14-slim-bookworm AS builder

WORKDIR /build
COPY packages packages
COPY workers/generation workers/generation
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip wheel --no-cache-dir --wheel-dir /wheels \
      ./packages/domain ./packages/auth ./packages/assets ./packages/assets_gcs \
      ./packages/generation_queue ./packages/model_gateway ./packages/model_gateway_openai \
      ./packages/persistence ./packages/prompts ./workers/generation

FROM python:3.12.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 jewelai && \
    useradd --uid 10001 --gid jewelai --no-create-home --shell /usr/sbin/nologin jewelai
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "jewelai_generation.runtime:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
