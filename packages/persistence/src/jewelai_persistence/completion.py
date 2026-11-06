"""Atomic completion unit; no API/prompt engine dependency or nested transactions."""

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from .models import DesignSessionRow, PromptCompletionRow
from .preparations import _authorize_and_lock, locked_reader
from .repository import PersistenceError


class CompletionStorageConflict(PersistenceError):
    pass


class CompletionStorageUnavailable(PersistenceError):
    pass


def completion_transaction(repository, sid, oid, principal_id, operation, *, write=True):
    try:
        with repository._session_factory.begin() as db:
            session = _authorize_and_lock(repository, db, oid, sid, principal_id)
            if write and db.bind.dialect.name == "sqlite":
                # PostgreSQL row lock above; SQLite needs an actual writer reservation.
                db.execute(
                    update(DesignSessionRow)
                    .where(DesignSessionRow.session_id == sid)
                    .values(current_revision_id=DesignSessionRow.current_revision_id)
                )
                db.refresh(session)
            rows = tuple(
                db.scalars(
                    select(PromptCompletionRow)
                    .where(
                        PromptCompletionRow.session_id == sid,
                        PromptCompletionRow.organization_id == oid,
                    )
                    .order_by(PromptCompletionRow.sequence_number)
                )
            )
            return operation(db, locked_reader(db), session, rows)
    except SQLAlchemyError as exc:
        original = getattr(exc, "orig", None)
        pg_code = getattr(original, "sqlstate", None)
        sqlite_code = getattr(original, "sqlite_errorcode", None)
        if pg_code in {"40001", "40P01", "23505"} or sqlite_code in {5, 6, 1555, 2067}:
            raise CompletionStorageConflict("Completion concurrent transaction conflict") from exc
        raise CompletionStorageUnavailable("Completion storage unavailable") from exc
