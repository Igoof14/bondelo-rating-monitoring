"""Доменные модели рейтинговых событий (общие для всех провайдеров)."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class ChangeType(Enum):
    """Тип изменения релиза относительно сохранённого состояния."""

    NEW = "new"
    CHANGED = "changed"


class ReleaseStub(BaseModel):
    """Лёгкая листинговая запись релиза.

    ``uid`` — стабильный идентификатор релиза у конкретного агентства
    (например, WordPress post id у НРА или slug у НКР).
    """

    uid: str
    url: str
    title: str = ""
    # Имя эмитента, если агентство отдаёт его прямо в листинге (АКРА).
    entity_name: str | None = None
    # Значение и прогноз, если они есть прямо в листинге отдельными колонками
    # («Эксперт РА»): там они чище, чем в заголовке релиза.
    rating_value: str | None = None
    outlook: str | None = None
    modified: datetime | None = None


class RatingEvent(BaseModel):
    """Распарсенное рейтинговое событие (релиз агентства)."""

    uid: str
    url: str
    release_id: str | None = None

    entity_name: str | None = None
    entity_type: str | None = None

    inn: str | None = None
    # Релиз может покрывать несколько облигационных выпусков (серий).
    isins: list[str] = []

    rating_action: str | None = None
    rating_value: str | None = None
    outlook: str | None = None

    publication_date: date | None = None
    modified: datetime | None = None
