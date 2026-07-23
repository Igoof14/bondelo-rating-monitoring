"""Точка входа Cloud Run Job: опросить агентства, сматчить, поставить задачи.

Один запуск = один прогон всех агентств → выход. Планирование запусков (каждые
N минут) выполняется снаружи (Cloud Scheduler → Cloud Run Job).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from ratings.alerts import build_user_alerts
from ratings.base_service import BaseRatingPoller
from ratings.cloud_tasks import enqueue_alerts
from ratings.db import dispose_engine
from ratings.enums import RatingAgency
from ratings.events import RatingEvent
from ratings.rating_nkr.service import NkrRatingPoller
from ratings.rating_nra.service import NraRatingPoller
from ratings.repository import PortfolioRepository, SubscriptionRepository
from ratings.settings import settings

logger = logging.getLogger(__name__)

# Провайдеры, опрашиваемые за один прогон.
POLLERS: list[type[BaseRatingPoller]] = [NraRatingPoller, NkrRatingPoller]


def _configure_logging() -> None:
    """Настраивает логирование по уровню из настроек."""
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run_poller(poller_cls: type[BaseRatingPoller]) -> list[RatingEvent]:
    """Прогоняет один провайдер, изолируя его ошибки от остальных."""
    try:
        return await poller_cls().run_check()
    except Exception:
        logger.exception("Сбой опроса провайдера %s", poller_cls.__name__)
        return []


async def run_all() -> int:
    """Опрашивает агентства, матчит изменения на портфели, ставит задачи.

    Returns:
        Количество пользователей, которым поставлены алерты.

    """
    results = await asyncio.gather(*(_run_poller(p) for p in POLLERS))
    events_by_agency: dict[RatingAgency, list[RatingEvent]] = {
        poller.agency: events for poller, events in zip(POLLERS, results) if events
    }

    total_events = sum(len(events) for events in events_by_agency.values())
    if not events_by_agency:
        logger.info("Прогон завершён: изменений нет")
        return 0

    subscriptions = await SubscriptionRepository.load_enabled()
    portfolios = await PortfolioRepository.load_portfolios()
    payloads = build_user_alerts(events_by_agency, subscriptions, portfolios)

    await enqueue_alerts(payloads)

    logger.info(
        "Прогон завершён: изменений — %d, получателей — %d", total_events, len(payloads)
    )
    return len(payloads)


def main() -> None:
    """Синхронная обёртка для Cloud Run Job с корректными кодами выхода."""
    _configure_logging()
    try:
        asyncio.run(_main_async())
    except Exception:
        logger.exception("Фатальная ошибка прогона")
        sys.exit(1)


async def _main_async() -> None:
    """Асинхронный сценарий с гарантированным закрытием пула БД."""
    try:
        await run_all()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    main()

