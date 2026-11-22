"""Exception identity without exception content."""

import traceback
from pathlib import PurePath

MAX_CAUSE_CHAIN = 5
MAX_ORIGIN_FRAMES = 8


def exception_diagnostics(exc: BaseException) -> dict[str, object]:
    """Return a safe identity for an exception: types and code locations only.

    Messages, arguments, local variables and source lines are never read, because
    they may carry provider payloads, credentials or private user content. The
    implicit ``__context__`` is followed even under ``from None`` so a sanitized
    boundary error still reveals which exception type caused it. Cycles and long
    chains are bounded.
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < MAX_CAUSE_CHAIN:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    frames = [
        f"{PurePath(frame.f_code.co_filename).name}:{lineno}:{frame.f_code.co_name}"
        for frame, lineno in traceback.walk_tb(chain[-1].__traceback__)
    ]
    return {
        "error_type": _type_name(exc),
        "error_chain": [_type_name(item) for item in chain],
        "error_origin": frames[-MAX_ORIGIN_FRAMES:],
    }


def _type_name(exc: BaseException) -> str:
    kind = type(exc)
    return f"{kind.__module__}.{kind.__qualname__}"
