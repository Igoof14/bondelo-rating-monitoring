"""Сервис полинга рейтингов НРА (тонкий провайдер на общем ядре)."""

from __future__ import annotations

from ratings.base_service import BaseRatingPoller
from ratings.enums import RatingAgency
from ratings.events import ChangeType, RatingEvent
from ratings.selection import select_changed

from . import config
from .client import NraClient


class NraRatingPoller(BaseRatingPoller):
    """Провайдер НРА: опрашивает ra-national.ru, остальное — общее ядро."""

    agency = RatingAgency.NRA

    async def _poll(
        self, known: dict[str, str | None]
    ) -> tuple[list[RatingEvent], dict[str, ChangeType]]:
        """Опрашивает НРА и возвращает новые/изменённые события с их типом."""
        async with NraClient() as client:
            stubs = await client.iter_release_stubs(config.MAX_PAGES)
            selected, change_by_uid = select_changed(stubs, known, config.EARLY_STOP_KNOWN)
            if not selected:
                return [], {}
            events = await client.fetch_many(selected)
        return events, change_by_uid
