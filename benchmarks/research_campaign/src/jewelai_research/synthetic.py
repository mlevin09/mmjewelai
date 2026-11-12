"""No model/network/GCP calls. Explicitly synthetic integration controls, not a quality judge."""

import base64
import hashlib
import time

from native_llm_bench.contracts import canonical
from native_llm_bench.transport import now, parse_response

from .contracts import PROFILES, TARGET, VERSION


def envelope(
    inputs, *, campaign_id="SYNTHETIC_CAMPAIGN", subject="synthetic-researcher", clock=time.time
):
    start = int(clock())
    return {
        "version": VERSION,
        "campaign_id": campaign_id,
        "mode": "SYNTHETIC",
        "assignment": "Synthetic adaptive experiment; no model quality or live execution claim.",
        "subject": subject,
        "target": TARGET.copy(),
        "pins": inputs.pins(),
        "allowed_sessions": [
            s["session_id"] for s in inputs.corpus["sessions"] if not s["holdout"]
        ],
        "allowed_profiles": list(PROFILES)
        + (list(inputs.policy["profiles"]) if inputs.policy else []),
        "scheduling_seed": 123,
        "inference_seed": 456,
        "period_start": start,
        "period_end": start + 3600,
        "max_wall_seconds": 600,
        "max_experiments": 3,
        "max_turns": 6,
        "max_attempts": 6,
        "budget": {
            "unit": "proxy_microunits",
            "hard_ceiling": 9,
            "soft_limit": 7,
            "attempt_cost": 1,
            "lifecycle_reserve": 1,
            "disk_reserve": 1,
            "agent_reserve": 1,
            "billing_guarantee": "NO_PAID_CALLS",
        },
    }


class SyntheticTransport:
    def __init__(self, *, truncate_control=True):
        self.truncate_control = truncate_control
        self.calls = []

    def __call__(self, config, payload):
        self.calls.append(payload)
        length = (
            self.truncate_control
            and config.temperature == 0
            and config.max_tokens < 256
            and "Answer the user's actual question" not in str(payload)
        )
        # Deliberately predictable controlled response. Never described as Qwen inference.
        raw = canonical(
            {
                "id": "synthetic-" + str(len(self.calls)),
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "SYNTHETIC"},
                        "finish_reason": "length" if length else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            }
        )
        r = {
            "started_at": now(),
            "ended_at": now(),
            "wall_seconds": 0.001,
            "http_status": 200,
            "status": None,
            "exception_family": None,
            "provider_may_have_executed": True,
            "raw_response_base64": base64.b64encode(raw).decode(),
            "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_json": None,
            "provider_response_id": None,
            "assistant_message": None,
            "finish_reason": None,
            "truncated": None,
            "metrics": {},
        }
        parse_response(r, raw)
        return r
