# Build from repository root; independent of the application/control-host image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/jewelai
COPY benchmarks/native_llm_stage1/pyproject.toml native/pyproject.toml
COPY benchmarks/native_llm_stage1/src native/src
COPY benchmarks/research_campaign/pyproject.toml research/pyproject.toml
COPY benchmarks/research_campaign/src research/src
RUN pip install --no-cache-dir ./native './research[https]' \
    && useradd --uid 10001 --no-create-home gateway
USER 10001:10001
CMD ["jewelai-research-https"]
