# linux/amd64 only. Base manifest was read from Docker Hub; no mutable runtime image tag.
FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS build
WORKDIR /build
COPY apps/stt/requirements-linux.lock /build/requirements-linux.lock
COPY apps/stt/requirements-build.lock /build/requirements-build.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock
RUN python -m pip install --no-cache-dir --no-build-isolation --require-hashes -r requirements-linux.lock
COPY apps/stt /build/stt
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation /build/stt
RUN python /build/stt/tools/package_model.py /opt/model

FROM python:3.12.14-slim-bookworm@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false \
    HF_HOME=/tmp/huggingface HOME=/tmp \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1
COPY --from=build /usr/local /usr/local
COPY --from=build /opt/model /opt/model
RUN groupadd --gid 10001 jewelai && \
    useradd --uid 10001 --gid jewelai --no-create-home --shell /usr/sbin/nologin jewelai && \
    chmod -R a-w /opt/model
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "jewelai_stt.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--log-level", "warning"]
