# Preprod-only overlay. The unchanged shared API image remains the base.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY --chown=0:0 . /app/knowledge-release/
RUN python /app/knowledge-release/_verify.py /app/knowledge-release --repository-root /app
