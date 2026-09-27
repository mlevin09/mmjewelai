FROM node:24-alpine AS builder

WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30-alpine3.24 AS runtime

COPY infra/docker/web.nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/docker/web-security-headers.conf /etc/nginx/snippets/jewelai-security-headers.conf
COPY infra/docker/web-entrypoint.sh /docker-entrypoint.d/40-jewelai-runtime-config.sh
COPY --from=builder --chown=101:101 /build/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
