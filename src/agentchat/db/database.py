from __future__ import annotations

from sqlalchemy import event
from sqlmodel import Session
from sqlmodel import SQLModel
from sqlmodel import create_engine

from .. import config

_engine = None


def engine():
    global _engine
    if _engine is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return _engine


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine())


def session() -> Session:
    # expire_on_commit=False so returned objects stay usable after the session closes.
    return Session(engine(), expire_on_commit=False)
