"""SQLAlchemy engine construction without application-global mutable state."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str, **kwargs) -> Engine:
    return create_engine(database_url, future=True, pool_pre_ping=True, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
