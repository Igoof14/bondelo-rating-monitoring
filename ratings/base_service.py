"""Базовый поллер рейтингов (общий для провайдеров).

Опрашивает источник, дедуплицирует и сохраняет релизы в БД, возвращает
новые/изменённые события. Матчинг на подписчиков/портфели и постановку задач
выполняет вызывающий код (``main.run_all``).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from .enums import RatingAgency
from .events import ChangeType, RatingEvent
from .repository import RatingReleaseRepository

logger = logging.getLogger(__name__)


class BaseRatingPoller(ABC):
    """Общий конвейер: опрос → дедуп → сохранение → изменённые события.

    Провайдер задаёт ``agency`` и реализует ``_poll`` (свой клиент/парсер).
    """

    agency: RatingAgency

    async def run_check(self) -> list[RatingEvent]:
        """Опрашивает агентство и возвращает новые/изменённые события."""
        agency = self.agency.value
        logger.info(f"Запуск проверки обновлений рейтингов {agency}")

        known = await RatingReleaseRepository.get_seen(self.agency)
        is_first_run = not known

        events, _change_by_uid = await self._poll(known)
        await RatingReleaseRepository.upsert_many(self.agency, events)

        if is_first_run:
            logger.info(
                f"Первый запуск {agency}: сохранено {len(events)} релизов, "
                "алерты не рассылаются"
            )
            return []

        if not events:
            logger.info(f"Новых изменений рейтингов {agency} нет")
            return []

        logger.info(f"Проверка обновлений рейтингов {agency}: {len(events)} изменени(й)")
        return events

    @abstractmethod
    async def _poll(
        self, known: dict[str, str | None]
    ) -> tuple[list[RatingEvent], dict[str, ChangeType]]:
        """Опрашивает источник и возвращает новые/изменённые события + их тип."""
        raise NotImplementedError
