"""Асинхронный клиент к сайту АКРА (acra-ratings.ru)."""

from __future__ import annotations

import asyncio
import logging
import ssl

import aiohttp

from ratings.events import RatingEvent, ReleaseStub
from ratings.proxy_pool import ProxyRotator, load_rotator
from ratings.throttle import Throttle

from . import config
from .parser import parse_listing, parse_release

logger = logging.getLogger(__name__)


def _build_ssl_context() -> ssl.SSLContext:
    """Системное хранилище + промежуточный сертификат АКРА (см. config.CA_BUNDLE)."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(config.CA_BUNDLE))
    return context


class AcraClient:
    """Клиент для перечисления и загрузки релизов рейтингов АКРА."""

    def __init__(
        self,
        base_url: str = config.BASE_URL,
        concurrency_limit: int = config.CONCURRENCY,
        timeout: int = config.TIMEOUT,
    ) -> None:
        """Инициализация клиента."""
        self._base = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._rotator: ProxyRotator = load_rotator()
        self._ssl = _build_ssl_context()
        self._throttle = Throttle(config.REQUEST_INTERVAL)

    async def __aenter__(self) -> AcraClient:
        """Открывает HTTP-сессию с браузерным User-Agent и SSL-контекстом АКРА."""
        self._session = aiohttp.ClientSession(
            timeout=self._timeout,
            headers={"User-Agent": config.USER_AGENT},
            connector=aiohttp.TCPConnector(ssl=self._ssl),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        """Закрывает HTTP-сессию."""
        if self._session:
            await self._session.close()

    @property
    def _client(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Клиент не инициализирован. Используйте 'async with AcraClient()'")
        return self._session

    async def iter_release_stubs(self, max_items: int = config.MAX_ITEMS) -> list[ReleaseStub]:
        """Возвращает верхние ``max_items`` листинговых записей (новейшие сверху)."""
        # LIST_PATH уже содержит query-строку с фильтром типа документа.
        url = f"{self._base}{config.LIST_PATH}"
        last_error: Exception | None = None
        # Листинг критичен — перебираем прокси до успеха.
        for _ in range(len(self._rotator.proxies)):
            proxy = self._rotator.next()
            try:
                await self._throttle.wait()
                async with self._semaphore, self._client.get(url, proxy=proxy) as response:
                    response.raise_for_status()
                    html = await response.text()
                return parse_listing(html)[:max_items]
            except Exception as e:
                last_error = e
                logger.warning(f"Листинг АКРА через прокси {proxy} не удался: {e}")

        logger.error(f"Не удалось загрузить листинг АКРА: {last_error}")
        return []

    async def fetch_release(self, stub: ReleaseStub) -> RatingEvent | None:
        """Загружает и парсит страницу одного релиза, повторяя при ошибке.

        Каждая попытка идёт через следующий прокси: 503 от WAF привязан к IP,
        поэтому смена прокси помогает надёжнее, чем просто пауза.
        """
        last_error: Exception | None = None
        for attempt in range(config.RETRIES):
            try:
                await self._throttle.wait()
                async with (
                    self._semaphore,
                    self._client.get(stub.url, proxy=self._rotator.next()) as response,
                ):
                    response.raise_for_status()
                    html = await response.text()
                return parse_release(html, stub)
            except Exception as e:
                last_error = e
                if attempt + 1 < config.RETRIES:
                    await asyncio.sleep(config.RETRY_DELAY * (attempt + 1))

        # Не бросаем: релиз не попадёт в снимок и будет перезабран на следующем
        # прогоне — там он снова окажется неизвестным.
        logger.error(f"Не удалось загрузить релиз {stub.url}: {last_error}")
        return None

    async def fetch_many(self, stubs: list[ReleaseStub]) -> list[RatingEvent]:
        """Конкурентно загружает страницы релизов, пропуская ошибочные."""
        tasks = [self.fetch_release(stub) for stub in stubs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        events: list[RatingEvent] = []
        for stub, result in zip(stubs, results, strict=False):
            if isinstance(result, BaseException):
                logger.error(f"Ошибка при загрузке релиза {stub.url}: {result}")
            elif result is not None:
                events.append(result)
        return events
