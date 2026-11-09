"""One local model process. A timed-out inference is terminated, never left running."""

import contextlib
import multiprocessing
import os
import threading
from pathlib import Path

from .artifacts import verify_artifacts
from .audio import SttError

LANGUAGES = {"ru", "en"}
# Orthographic hints only, never a template sentence or a transcript replacement.
# New terms must be qualified against independent/no-speech controls before promotion.
HOTWORDS = {
    "ru": (
        "золотой, серебряный, платиновый, овальный, круглый, квадратный, груша, "
        "бриллиант, сапфир, рубин, изумруд, жемчужина, крапан, крапаны, крапановая закрепка"
    ),
    "en": "pear cut, prong setting",
}


def _model_process(connection, model_dir: str) -> None:
    # Libraries must not emit user input, results, or raw exceptions to container logs.
    with (
        open(os.devnull, "w") as null,
        contextlib.redirect_stdout(null),
        contextlib.redirect_stderr(null),
    ):
        try:
            os.environ.update(
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                HF_HUB_DISABLE_TELEMETRY="1",
                DO_NOT_TRACK="1",
                TOKENIZERS_PARALLELISM="false",
            )
            verify_artifacts(Path(model_dir))
            import numpy as np
            from faster_whisper import WhisperModel

            model = WhisperModel(
                model_dir,
                local_files_only=True,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                num_workers=1,
            )
            connection.send(("ready",))
            while True:
                pcm, language = connection.recv()
                samples = np.frombuffer(pcm, dtype="<f4")
                segments, info = model.transcribe(
                    samples,
                    language=language,
                    task="transcribe",
                    beam_size=5,
                    best_of=1,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    hotwords=HOTWORDS.get(language),
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                if len(text) > 8192:
                    connection.send(("error",))
                elif info.language not in LANGUAGES:
                    connection.send(("unsupported_language",))
                else:
                    connection.send(("result", text, info.language))
                # Do not retain the last caller's PCM/result while waiting for another request.
                del pcm, language, samples, segments, info, text
        except (EOFError, BrokenPipeError):
            return
        except Exception:
            # The third-party boundary deliberately transports no provider/exception payload.
            with contextlib.suppress(OSError):
                connection.send(("error",))


class LocalEngine:
    def __init__(self, model_dir: str = "/opt/model"):
        self.model_dir = model_dir
        self.lock = threading.Lock()
        self.process = None
        self.connection = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready and self.process is not None and self.process.is_alive()

    def start(self) -> None:
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=_model_process, args=(child, self.model_dir), daemon=True
        )
        self.process.start()
        child.close()
        try:
            self._ready = self.connection.poll(210) and self.connection.recv() == ("ready",)
        except (EOFError, OSError):
            self._ready = False
        if not self.ready:
            self.close()
            raise RuntimeError("stt_startup_failed") from None

    def transcribe(self, pcm: bytes, language: str | None) -> tuple[str, str]:
        if not self.lock.acquire(blocking=False):
            raise SttError("stt_busy", 429)
        try:
            if not self.ready:
                raise SttError("stt_unavailable", 503)
            self.connection.send((pcm, language))
            if not self.connection.poll(40):
                self.close()
                raise SttError("stt_timeout", 504)
            response = self.connection.recv()
            if response[0] == "unsupported_language":
                raise SttError("unsupported_language")
            if response[0] != "result":
                self.close()
                raise SttError("stt_unavailable", 503)
            return response[1], response[2]
        except (EOFError, OSError):
            self.close()
            raise SttError("stt_unavailable", 503) from None
        finally:
            self.lock.release()

    def close(self) -> None:
        self._ready = False
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(2)
        if self.connection is not None:
            self.connection.close()
