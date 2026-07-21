"""Сервис полинга рейтингов НКР (тонкий провайдер на общем ядре)."""

from __future__ import annotations

from ratings.base_service import BaseRatingPoller
from ratings.enums import RatingAgency
from ratings.events import ChangeType, RatingEvent
from ratings.selection import select_changed

from . import config
from .client import NkrClient


class NkrRatingPoller(BaseRatingPoller):
    """Провайдер НКР: опрашивает ratings.ru, остальное — общее ядро."""

    agency = RatingAgency.NKR

    async def _poll(
        self, known: dict[str, str | None]
    ) -> tuple[list[RatingEvent], dict[str, ChangeType]]:
        """Опрашивает НКР и возвращает новые/изменённые события с их типом."""
        async with NkrClient() as client:
            stubs = await client.iter_release_stubs(config.MAX_ITEMS)
            selected, change_by_uid = select_changed(stubs, known, config.EARLY_STOP_KNOWN)
            if not selected:
                return [], {}
            events = await client.fetch_many(selected)
        return events, change_by_uid
