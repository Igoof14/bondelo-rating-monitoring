"""Асинхронный слой доступа к БД (замена монорепного ``core.database``).

PostgreSQL через SQLAlchemy async + asyncpg. Схема таблиц уже существует —
сервис только читает/пишет, миграции не выполняет.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .settings import settings


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Открывает сессию; откатывает при ошибке и всегда закрывает.

    Коммит выполняет вызывающий код (как в исходной реализации).
    """
    session = async_session()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Закрывает пул соединений (в конце жизни Job)."""
    await engine.dispose()
