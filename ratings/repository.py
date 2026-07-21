"""Доступ к состоянию дедупа рейтинговых релизов."""

from __future__ import annotations

import logging

from sqlalchemy import select

from .db import session_scope
from .enums import RatingAgency
from .events import ChangeType, RatingEvent
from .models import RatingRelease

logger = logging.getLogger(__name__)


class RatingReleaseRepository:
    """Состояние дедупа увиденных релизов (общая таблица на провайдеров)."""

    @classmethod
    async def get_seen(cls, agency: RatingAgency) -> dict[str, str | None]:
        """Возвращает снимок ``{uid: modified}`` увиденных релизов агентства."""
        try:
            async with session_scope() as session:
                result = await session.execute(
                    select(RatingRelease.uid, RatingRelease.modified).where(
                        RatingRelease.agency == agency.value
                    )
                )
                return {uid: modified for uid, modified in result.all()}
        except Exception as e:
            logger.error(f"Ошибка при получении снимка релизов {agency.value}: {e}")
            return {}

    @classmethod
    async def upsert_many(cls, agency: RatingAgency, events: list[RatingEvent]) -> None:
        """Создаёт или обновляет релизы агентства по ``uid``."""
        if not events:
            return

        async with session_scope() as session:
            for event in events:
                result = await session.execute(
                    select(RatingRelease).where(
                        RatingRelease.agency == agency.value,
                        RatingRelease.uid == event.uid,
                    )
                )
                release = result.scalar_one_or_none()

                if release is None:
                    release = RatingRelease(agency=agency.value, uid=event.uid)
                    session.add(release)

                release.url = event.url
                release.release_id = event.release_id
                release.inn = event.inn
                release.isins = ", ".join(event.isins) if event.isins else None
                release.entity_name = event.entity_name
                release.entity_type = event.entity_type
                release.rating_action = event.rating_action
                release.rating_value = event.rating_value
                release.outlook = event.outlook
                release.publication_date = event.publication_date
                release.modified = event.modified.isoformat() if event.modified else None

            await session.commit()

    @staticmethod
    def classify(
        uid: str, modified_iso: str | None, known: dict[str, str | None]
    ) -> ChangeType | None:
        """Классифицирует релиз: NEW (неизвестен), CHANGED (modified новее), иначе None."""
        if uid not in known:
            return ChangeType.NEW
        if modified_iso is not None and modified_iso != known[uid]:
            return ChangeType.CHANGED
        return None
