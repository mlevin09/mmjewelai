"""SQLAlchemy engine construction without application-global mutable state."""

import os
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class DatabasePoolConfig:
    """Bounded production pool settings; SQLite keeps its native test pool behavior."""

    pool_size: int = 5
    max_overflow: int = 2
    pool_timeout_seconds: int = 30
    pool_recycle_seconds: int = 1800

    def __post_init__(self) -> None:
        _bounded("DB_POOL_SIZE", self.pool_size, 1, 50)
        _bounded("DB_MAX_OVERFLOW", self.max_overflow, 0, 50)
        _bounded("DB_POOL_TIMEOUT_SECONDS", self.pool_timeout_seconds, 1, 300)
        _bounded("DB_POOL_RECYCLE_SECONDS", self.pool_recycle_seconds, 60, 86400)

    @classmethod
    def from_environment(cls) -> "DatabasePoolConfig":
        return cls(
            pool_size=_environment_integer("DB_POOL_SIZE", cls.pool_size),
            max_overflow=_environment_integer("DB_MAX_OVERFLOW", cls.max_overflow),
            pool_timeout_seconds=_environment_integer(
                "DB_POOL_TIMEOUT_SECONDS", cls.pool_timeout_seconds
            ),
            pool_recycle_seconds=_environment_integer(
                "DB_POOL_RECYCLE_SECONDS", cls.pool_recycle_seconds
            ),
        )


def create_database_engine(
    database_url: str,
    *,
    pool_config: DatabasePoolConfig | None = None,
    **kwargs,
) -> Engine:
    if not database_url.startswith("sqlite"):
        config = pool_config or DatabasePoolConfig.from_environment()
        kwargs.setdefault("pool_size", config.pool_size)
        kwargs.setdefault("max_overflow", config.max_overflow)
        kwargs.setdefault("pool_timeout", config.pool_timeout_seconds)
        kwargs.setdefault("pool_recycle", config.pool_recycle_seconds)
    return create_engine(database_url, future=True, pool_pre_ping=True, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _environment_integer(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _bounded(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
