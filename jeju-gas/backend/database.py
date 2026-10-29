"""SQLite + SQLModel 엔진/세션."""
from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from config import get_settings


def make_engine(url: str) -> Engine:
    """DB URL로 엔진을 만든다. 메모리 SQLite는 단일 커넥션을 공유한다(테스트용)."""
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


@lru_cache
def get_engine() -> Engine:
    """전역 엔진."""
    return make_engine(get_settings().database_url)


def init_db(engine: Engine | None = None) -> None:
    """테이블을 생성한다."""
    from alerts import models  # noqa: F401  (테이블 등록)

    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI 의존성용 세션."""
    with Session(get_engine()) as session:
        yield session
