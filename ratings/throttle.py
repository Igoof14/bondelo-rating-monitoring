"""Ограничитель темпа запросов (общий для провайдеров с WAF по частоте)."""

from __future__ import annotations

import asyncio


class Throttle:
    """Выдерживает минимальный интервал между стартами запросов.

    У части агентств ограничитель — частота, а не параллельность (АКРА,
    «Эксперт РА»), поэтому разносим именно моменты отправки. Сон под
    блокировкой: так очередь выстраивается честно, а не будит все корутины
    разом.
    """

    def __init__(self, interval: float) -> None:
        """Создаёт троттл с заданным интервалом в секундах."""
        self._interval = interval
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        """Ждёт до момента, когда можно отправлять следующий запрос."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            delay = self._next_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = loop.time() + self._interval
