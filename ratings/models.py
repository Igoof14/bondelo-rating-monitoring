"""Модель состояния дедупа рейтинговых релизов."""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class RatingRelease(Base):
    """Увиденный релиз рейтинга (состояние дедупа полинга).

    Единая таблица на всех провайдеров: одна строка на пару (agency, uid).
    """

    __tablename__ = "rating_releases"
    __table_args__ = (UniqueConstraint("agency", "uid", name="uq_rating_releases_agency_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agency: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Стабильный идентификатор релиза у агентства (post id / slug).
    uid: Mapped[str] = mapped_column(String(128), nullable=False)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    inn: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    isins: Mapped[str | None] = mapped_column(Text, nullable=True)

    entity_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    rating_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rating_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outlook: Mapped[str | None] = mapped_column(String(64), nullable=True)

    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # ISO-строка сигнала изменения (для агентств, где релизы меняются).
    modified: Mapped[str | None] = mapped_column(String(32), nullable=True)

    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        """Представление модели."""
        return f"<RatingRelease(agency={self.agency}, uid={self.uid}, inn={self.inn})>"
