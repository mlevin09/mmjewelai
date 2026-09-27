#!/bin/sh
set -eu

if [ -z "${JEWELAI_WEB_CONFIG_JSON:-}" ]; then
  echo "JEWELAI_WEB_CONFIG_JSON is required" >&2
  exit 1
fi

case "$JEWELAI_WEB_CONFIG_JSON" in
  \{*\}) ;;
  *)
    echo "JEWELAI_WEB_CONFIG_JSON must be a JSON object" >&2
    exit 1
    ;;
esac

printf 'window.__JEWELAI_RUNTIME_CONFIG__ = %s;\n' "$JEWELAI_WEB_CONFIG_JSON" \
  > /usr/share/nginx/html/runtime-config.js
