"""One direct numeric-loopback HTTP request; no proxies, redirects, SDKs or tools."""

import base64
import hashlib
import http.client
import math
import time
from datetime import UTC, datetime

from .contracts import InvalidArtifact, canonical, decode, loopback_address

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def now():
    return datetime.now(UTC).isoformat()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def parse_response(record, raw):
    try:
        data = decode(raw)
        if not isinstance(data, dict):
            raise InvalidArtifact("invalid response")
        record["response_json"] = data
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise InvalidArtifact("invalid choices")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise InvalidArtifact("invalid assistant role")
        if (
            message.get("tool_calls")
            or message.get("function_call")
            or message.get("reasoning_content")
        ):
            record["status"] = "PROMPT_TEMPLATE"
            return
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            record["status"] = "MISSING_CONTENT"
            return
        record["assistant_message"] = {"role": "assistant", "content": content}
        record["finish_reason"] = choice.get("finish_reason")
        record["provider_response_id"] = data.get("id")
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise InvalidArtifact("missing response identity")
        usage = data.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise InvalidArtifact("invalid usage")
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key) if usage else None
            if value is not None and (type(value) is not int or value < 0):
                raise InvalidArtifact("invalid token count")
            record["metrics"][key] = value
        timings = data.get("timings")
        if isinstance(timings, dict) and _number(timings.get("predicted_per_second")):
            record["metrics"]["server_decode_tokens_per_second"] = timings["predicted_per_second"]
        truncated = choice.get("finish_reason") == "length" or data.get("truncated") is True
        record["truncated"] = truncated
        if truncated:
            record["status"] = "TRUNCATED"
        elif choice.get("finish_reason") != "stop":
            record["status"] = "INVALID_API_RESPONSE"
        else:
            record["status"] = "COMPLETED"
    except (InvalidArtifact, TypeError, ValueError):
        record["status"] = "INVALID_API_RESPONSE"


def request(config, payload):
    """Full raw bytes retained even on errors; no raw exception messages are emitted."""
    start = time.monotonic()
    record = {
        "started_at": now(),
        "ended_at": None,
        "wall_seconds": None,
        "http_status": None,
        "status": "TRANSPORT",
        "exception_family": None,
        "provider_may_have_executed": False,
        "raw_response_base64": None,
        "raw_response_sha256": None,
        "response_json": None,
        "provider_response_id": None,
        "assistant_message": None,
        "finish_reason": None,
        "truncated": None,
        "metrics": {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "ttft_seconds": None,
            "cpu_percent": None,
            "ram_bytes": None,
            "server_decode_tokens_per_second": None,
            "completion_tokens_per_wall_second": None,
        },
    }
    u = loopback_address(config.endpoint)  # Enforce even for callers bypassing the CLI.
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=config.timeout_seconds)
    raw = bytearray()
    try:
        conn.connect()
        sock = conn.sock
        remaining = config.timeout_seconds - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError
        sock.settimeout(remaining)
        record["provider_may_have_executed"] = True
        conn.request(
            "POST",
            "/v1/chat/completions",
            canonical(payload),
            {"Content-Type": "application/json", "Accept": "application/json"},
        )
        remaining = config.timeout_seconds - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError
        sock.settimeout(remaining)
        response = conn.getresponse()
        record["http_status"] = response.status
        while True:
            remaining = config.timeout_seconds - (time.monotonic() - start)
            if remaining <= 0:
                raise TimeoutError
            if sock.fileno() >= 0:
                sock.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE_BYTES:
                record["status"] = "INVALID_API_RESPONSE"
                break
            if not chunk:
                if response.length not in (None, 0):
                    raise http.client.IncompleteRead(bytes(raw), response.length)
                if response.status == 200:
                    parse_response(record, bytes(raw))
                else:
                    record["status"] = "SERVER_ERROR" if response.status >= 500 else "HTTP_ERROR"
                    try:
                        error = decode(bytes(raw)).get("error", {})
                        if isinstance(error, dict) and error.get("code") in (
                            "chat_template_error",
                            "unsupported_template",
                            "context_length_exceeded",
                        ):
                            record["status"] = "PROMPT_TEMPLATE"
                    except (InvalidArtifact, AttributeError):
                        pass
                break
    except TimeoutError:
        record["status"] = "TIMEOUT"
        record["exception_family"] = "timeout"
    except ConnectionRefusedError:
        record["status"] = "ENDPOINT_UNAVAILABLE"
        record["exception_family"] = "connection_refused"
    except (OSError, http.client.HTTPException) as exc:
        record["status"] = "TRANSPORT"
        record["exception_family"] = type(exc).__name__
    finally:
        conn.close()
    record["ended_at"] = now()
    record["wall_seconds"] = time.monotonic() - start
    record["raw_response_base64"] = base64.b64encode(raw).decode("ascii")
    record["raw_response_sha256"] = hashlib.sha256(raw).hexdigest()
    count = record["metrics"]["completion_tokens"]
    if count is not None and record["wall_seconds"] > 0:
        record["metrics"]["completion_tokens_per_wall_second"] = count / record["wall_seconds"]
    return record
