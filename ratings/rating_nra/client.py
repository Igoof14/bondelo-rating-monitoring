"""Асинхронный клиент к сайту НРА (ra-national.ru)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import aiohttp

from ratings.events import RatingEvent, ReleaseStub
from ratings.proxy_pool import ProxyRotator, load_rotator

from . import config
from .parser import parse_release

logger = logging.getLogger(__name__)


def _parse_iso(value: str | None) -> datetime | None:
    """Парсит ISO-дату из REST-ответа, либо ``None``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _stub_from_item(item: dict) -> ReleaseStub:
    """Преобразует элемент REST-листинга в ``ReleaseStub``."""
    return ReleaseStub(
        uid=str(item["id"]),
        url=str(item["link"]),
        title=str(item.get("title", {}).get("rendered", "")),
        modified=_parse_iso(item.get("modified")),
    )


class NraClient:
    """Клиент для перечисления и загрузки релизов рейтингов НРА."""

    def __init__(
        self,
        base_url: str = config.BASE_URL,
        per_page: int = config.PER_PAGE,
        concurrency_limit: int = config.CONCURRENCY,
        timeout: int = config.TIMEOUT,
    ) -> None:
        """Инициализация клиента."""
        self._base = base_url.rstrip("/")
        self._per_page = per_page
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._rotator: ProxyRotator = load_rotator()

    async def __aenter__(self) -> NraClient:
        """Открывает HTTP-сессию."""
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self

    async def __aexit__(self, *args: object) -> None:
        """Закрывает HTTP-сессию."""
        if self._session:
            await self._session.close()

    @property
    def _client(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Клиент не инициализирован. Используйте 'async with NraClient()'")
        return self._session

    async def iter_release_stubs(self, max_pages: int = config.MAX_PAGES) -> list[ReleaseStub]:
        """Возвращает листинговые записи релизов, новейшие по ``modified`` первыми.

        Args:
            max_pages: Сколько страниц REST-листинга запросить.

        Returns:
            Список ``ReleaseStub`` в порядке modified-desc.

        """
        stubs: list[ReleaseStub] = []

        for page in range(1, max_pages + 1):
            url = (
                f"{self._base}{config.REST_PATH}"
                f"?per_page={self._per_page}&page={page}"
                f"&orderby=modified&order=desc&_fields=id,link,title,modified"
            )
            items, total_pages = await self._get_listing_page(url, page)
            if items is None:
                break

            if not items:
                break

            stubs.extend(_stub_from_item(item) for item in items)

            if total_pages and page >= int(total_pages):
                break

        return stubs

    async def _get_listing_page(self, url: str, page: int) -> tuple[list[dict] | None, str | None]:
        """Грузит одну страницу листинга, перебирая прокси до успеха.

        Returns:
            ``(items, total_pages)``; ``items=None`` — страницу взять не удалось.

        """
        last_error: Exception | None = None
        for _ in range(len(self._rotator.proxies)):
            proxy = self._rotator.next()
            try:
                async with self._semaphore, self._client.get(url, proxy=proxy) as response:
                    response.raise_for_status()
                    items = await response.json()
                    return items, response.headers.get("X-WP-TotalPages")
            except Exception as e:
                last_error = e
                logger.warning(f"Листинг НРА (стр. {page}) через прокси {proxy} не удался: {e}")

        logger.error(f"Не удалось загрузить листинг НРА (страница {page}): {last_error}")
        return None, None

    async def fetch_release(self, stub: ReleaseStub) -> RatingEvent | None:
        """Загружает и парсит страницу одного релиза."""
        async with (
            self._semaphore,
            self._client.get(stub.url, proxy=self._rotator.next()) as response,
        ):
            response.raise_for_status()
            html = await response.text()
        return parse_release(html, stub)

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
