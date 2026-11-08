"""Cloud Run IAM is the authentication boundary; this app is never a public API."""

import asyncio
import contextlib
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .artifacts import MODEL_ID, REVISION
from .audio import FORMATS, MAX_BYTES, SttError, decode_audio
from .engine import LocalEngine


def create_app(*, engine=None, decoder=decode_audio) -> FastAPI:
    engine = engine if engine is not None else LocalEngine()

    @contextlib.asynccontextmanager
    async def lifespan(_):
        await asyncio.to_thread(engine.start)
        try:
            yield
        finally:
            await asyncio.to_thread(engine.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    busy = asyncio.Lock()

    @app.exception_handler(SttError)
    async def stt_error(_, error: SttError):
        return JSONResponse({"error": {"code": error.code}}, status_code=error.status)

    @app.get("/health")
    async def health():
        return JSONResponse({"ready": engine.ready}, status_code=200 if engine.ready else 503)

    @app.post("/internal/v1/transcriptions")
    async def transcribe(request: Request):
        # No session identifier, database access, text intake, or automatic decision submission.
        if set(request.query_params) - {"language"}:
            raise SttError("invalid_request", 400)
        language = request.query_params.get("language")
        if language not in (None, "ru", "en"):
            raise SttError("unsupported_language")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in FORMATS:
            raise SttError("unsupported_audio", 415)
        if busy.locked():
            raise SttError("stt_busy", 429)
        async with busy:
            started = time.monotonic()
            content = bytearray()
            try:
                try:
                    async with asyncio.timeout(10):
                        async for chunk in request.stream():
                            if len(content) + len(chunk) > MAX_BYTES:
                                raise SttError("audio_too_large", 413)
                            content.extend(chunk)
                except TimeoutError:
                    raise SttError("audio_upload_timeout", 408) from None
                audio = await asyncio.to_thread(decoder, bytes(content), content_type)
                if audio.silent:
                    text, detected = "", None
                else:
                    text, detected = await asyncio.to_thread(engine.transcribe, audio.pcm, language)
                if not text:
                    detected = None
                return {
                    "schema_version": "1.0.0",
                    "status": "transcribed" if text else "silence",
                    "text": text,
                    "language": detected,
                    "duration_ms": audio.duration_ms,
                    "processing_ms": round((time.monotonic() - started) * 1000),
                    "model": MODEL_ID,
                    "model_revision": REVISION,
                }
            finally:
                content.clear()

    return app
