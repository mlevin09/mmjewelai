"""Small structured logger that never serializes provider payloads or exceptions."""

import json
import logging


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = dict(getattr(record, "jewelai_fields", {}))
        return json.dumps(
            {
                "severity": record.levelname,
                "message": record.getMessage(),
                **fields,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_worker_logger() -> logging.Logger:
    logger = logging.getLogger("jewelai.generation")
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "jewelai_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        handler.jewelai_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    logger.info(event.replace("_", " "), extra={"jewelai_fields": {"event": event, **fields}})
