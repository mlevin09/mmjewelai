"""Explicit startup-only composition over the existing ConversationModel protocol.

This is deployment configuration, not a catalog, user selector or State authority.
Only approved registered profiles may be selected. No model or secret is invented.
"""

import json
import os
from dataclasses import fields

from .conversation_qwen import QwenConversationAdapter, QwenConversationConfig

ADAPTERS = {"llama_cpp": QwenConversationAdapter, "qwen": QwenConversationAdapter}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate conversational configuration key")
        value[key] = item
    return value


def select_profile(raw, active, *, environment=None):
    environment = os.environ if environment is None else environment
    try:
        rows = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(rows, list) or len(rows) > 16:
            raise ValueError
        registry = {}
        allowed = {f.name for f in fields(QwenConversationConfig)} - {"provider"}
        required = {
            "profile_id",
            "endpoint",
            "model",
            "model_sha256",
            "runtime_build",
            "context_tokens",
        }
        for row in rows:
            if not isinstance(row, dict) or set(row) - allowed - {"engine", "approved"}:
                raise ValueError
            if not required <= set(row) or row.get("engine") != "llama_cpp":
                raise ValueError
            if type(row.get("approved")) is not bool:
                raise ValueError
            config = QwenConversationConfig(
                **{k: v for k, v in row.items() if k in allowed}, provider="llama_cpp"
            )
            if config.profile_id in registry:
                raise ValueError
            registry[config.profile_id] = (config, row["approved"])
        if active == "disabled":
            return None
        config, approved = registry[active]
        if not approved:
            raise ValueError
        if config.auth_mode == "bearer_env":
            secret = environment.get(config.auth_env, "")
            if not secret or any(c in secret for c in "\r\n"):
                raise ValueError
        return config
    except (TypeError, KeyError, ValueError):
        # No raw configuration, endpoint, secret or parsing exception is disclosed.
        raise ValueError("Invalid, missing or unauthorized conversational profile") from None


def compose_conversation_model(config):
    if config is None:
        return None
    try:
        adapter = ADAPTERS[config.provider]
    except KeyError:
        raise ValueError("Unsupported conversational engine") from None
    return adapter(config)
