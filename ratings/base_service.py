"""Базовый поллер рейтингов (общий для провайдеров).

Опрашивает источник, дедуплицирует и сохраняет релизы в БД, возвращает ссылки
на новые/изменённые релизы. Матчинг подписчиков/портфелей и рассылку выполняет
отдельный воркер (в боте), которому ставится задача в Cloud Tasks.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from .cloud_tasks import ReleaseRef
from .enums import RatingAgency
from .events import ChangeType, RatingEvent
from .repository import RatingReleaseRepository

logger = logging.getLogger(__name__)


class BaseRatingPoller(ABC):
    """Общий конвейер: опрос → дедуп → сохранение → ссылки на изменения.

    Провайдер задаёт ``agency`` и реализует ``_poll`` (свой клиент/парсер).
    """

    agency: RatingAgency

    async def run_check(self) -> list[ReleaseRef]:
        """Опрашивает агентство и возвращает ссылки на новые/изменённые релизы."""
        agency = self.agency.value
        logger.info(f"Запуск проверки обновлений рейтингов {agency}")

        known = await RatingReleaseRepository.get_seen(self.agency)
        is_first_run = not known

        events, change_by_uid = await self._poll(known)
        await RatingReleaseRepository.upsert_many(self.agency, events)

        if is_first_run:
            logger.info(
                f"Первый запуск {agency}: сохранено {len(events)} релизов, "
                "задача на алерт не ставится"
            )
            return []

        if not events:
            logger.info(f"Новых изменений рейтингов {agency} нет")
            return []

        refs = [
            ReleaseRef(
                agency=agency,
                uid=event.uid,
                change_type=change_by_uid.get(event.uid, ChangeType.NEW).value,
            )
            for event in events
        ]
        logger.info(f"Проверка обновлений рейтингов {agency}: {len(refs)} изменени(й)")
        return refs

    @abstractmethod
    async def _poll(
        self, known: dict[str, str | None]
    ) -> tuple[list[RatingEvent], dict[str, ChangeType]]:
        """Опрашивает источник и возвращает новые/изменённые события + их тип."""
        raise NotImplementedError
