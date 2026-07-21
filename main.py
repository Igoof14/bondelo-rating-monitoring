"""Точка входа Cloud Run Job: опросить агентства, сохранить, поставить задачу.

Один запуск = один прогон всех агентств → выход. Планирование запусков (каждые
N минут) выполняется снаружи (Cloud Scheduler → Cloud Run Job).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from ratings.base_service import BaseRatingPoller
from ratings.cloud_tasks import ReleaseRef, enqueue_alert
from ratings.db import dispose_engine
from ratings.rating_nkr.service import NkrRatingPoller
from ratings.rating_nra.service import NraRatingPoller
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


async def _run_poller(poller_cls: type[BaseRatingPoller]) -> list[ReleaseRef]:
    """Прогоняет один провайдер, изолируя его ошибки от остальных."""
    try:
        return await poller_cls().run_check()
    except Exception:
        logger.exception("Сбой опроса провайдера %s", poller_cls.__name__)
        return []


async def run_all() -> int:
    """Опрашивает все агентства и ставит одну задачу на алерт.

    Returns:
        Количество изменённых релизов, попавших в задачу.

    """
    results = await asyncio.gather(*(_run_poller(p) for p in POLLERS))
    refs: list[ReleaseRef] = [ref for batch in results for ref in batch]

    await enqueue_alert(refs)

    logger.info("Прогон завершён: изменений — %d", len(refs))
    return len(refs)


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
