#!/usr/bin/env bash
set -euo pipefail
python -m pip install \
  -e './packages/domain[test]' \
  -e './packages/auth[test]' \
  -e './packages/auth_oidc[test]' \
  -e './packages/auth_identity_platform[test]' \
  -e './packages/generation_queue[test]' \
  -e './packages/generation_queue_gcp[test]' \
  -e './packages/prompts[test]' \
  -e './packages/model_gateway[test]' \
  -e './packages/assets[test]' \
  -e './packages/assets_gcs[test]' \
  -e './packages/persistence' \
  -e './packages/model_gateway_google[test]' \
  -e './packages/model_gateway_openai[test]' \
  -e './workers/generation[test]' \
  -e './packages/parser[test]' \
  -e './packages/text_understanding_google[test]' \
  -e './apps/api[test]'
