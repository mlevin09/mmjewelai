"""Bounded audio decoding in a separate, resource-limited process; no URLs or temp files."""

import array
import math
import subprocess
import sys
from dataclasses import dataclass

MAX_BYTES = 10 * 1024 * 1024
SAMPLE_RATE = 16000
MAX_SECONDS = 60
FORMATS = {"audio/wav": "wav", "audio/webm": "matroska,webm", "audio/ogg": "ogg"}


class SttError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Audio:
    pcm: bytes

    def __post_init__(self):
        if not self.pcm or len(self.pcm) % 4:
            raise SttError("invalid_audio")
        samples = array.array("f", self.pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        if not all(math.isfinite(value) for value in samples):
            raise SttError("invalid_audio")

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) * 1000 // (4 * SAMPLE_RATE)

    @property
    def silent(self) -> bool:
        samples = array.array("f", self.pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        # Only digital/near-digital silence; this is not a speech/activity classifier.
        return all(abs(x) <= 0.00001 for x in samples)


def decode_audio(content: bytes, content_type: str) -> Audio:
    if content_type not in FORMATS:
        raise SttError("unsupported_audio", 415)
    if len(content) > MAX_BYTES:
        raise SttError("audio_too_large", 413)
    if not content:
        raise SttError("invalid_audio")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "jewelai_stt.decode_worker", FORMATS[content_type]],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise SttError("audio_decode_timeout", 504) from None
    if result.returncode or not result.stdout or len(result.stdout) % 4:
        raise SttError("invalid_audio")
    if len(result.stdout) > SAMPLE_RATE * MAX_SECONDS * 4:
        raise SttError("audio_too_long", 413)
    return Audio(result.stdout)
