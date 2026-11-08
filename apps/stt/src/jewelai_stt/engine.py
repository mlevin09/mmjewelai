"""One local model process. A timed-out inference is terminated, never left running."""

import contextlib
import multiprocessing
import os
import threading
from pathlib import Path

from .artifacts import verify_artifacts
from .audio import SAMPLE_RATE, SttError

LANGUAGES = {"Russian": "ru", "English": "en"}


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
            import torch
            from qwen_asr import Qwen3ASRModel

            torch.set_num_threads(2)
            model = Qwen3ASRModel.from_pretrained(
                model_dir,
                local_files_only=True,
                dtype=torch.bfloat16,
                device_map="cuda:0",
                max_inference_batch_size=1,
                max_new_tokens=1024,
            )
            connection.send(("ready",))
            while True:
                pcm, language = connection.recv()
                result = model.transcribe(
                    audio=(np.frombuffer(pcm, dtype="<f4"), SAMPLE_RATE),
                    language={"ru": "Russian", "en": "English"}.get(language),
                )[0]
                text = result.text.strip()
                if len(text) > 8192:
                    connection.send(("error",))
                elif result.language not in LANGUAGES:
                    connection.send(("unsupported_language",))
                else:
                    connection.send(("result", text, LANGUAGES[result.language]))
                # Do not retain the last caller's PCM/result while waiting for another request.
                del pcm, language, result, text
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
