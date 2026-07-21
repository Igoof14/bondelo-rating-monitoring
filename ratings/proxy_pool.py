"""Пул прокси для скрейпинга рейтингов: парсинг, нормализация, ротация."""

from __future__ import annotations

import logging
import re

from .settings import settings

logger = logging.getLogger(__name__)

# Разделители элементов списка прокси в .env.
_SPLIT_RE = re.compile(r"[,\n\s]+")
# Схемы, которые принимаем как готовый URL.
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def normalize_proxy(raw: str) -> str:
    """Нормализует строку прокси в URL ``http://[user:pass@]host:port``.

    Поддерживает: готовый URL со схемой; ``ip:port:user:pass``; ``host:port``.

    Raises:
        ValueError: Если строку нельзя распознать.

    """
    value = raw.strip()
    if not value:
        raise ValueError("пустая строка прокси")

    if _SCHEME_RE.match(value):
        return value

    parts = value.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"

    raise ValueError(f"не распознан формат прокси: {raw!r}")


def load_proxies() -> list[str | None]:
    """Загружает пул прокси для рейтингов из конфигурации.

    Берёт ``config.ratings_proxies`` (список), иначе одиночный
    ``config.ratings_proxy``. Если ничего не задано — ``[None]`` (прямое
    соединение).
    """
    raw = settings.ratings_proxies or settings.ratings_proxy
    if not raw:
        return [None]

    proxies: list[str | None] = []
    for token in _SPLIT_RE.split(raw):
        if not token:
            continue
        try:
            proxies.append(normalize_proxy(token))
        except ValueError as e:
            logger.warning("Пропущен некорректный прокси: %s", e)

    return proxies or [None]


class ProxyRotator:
    """Round-robin по пулу прокси (``None`` = прямое соединение)."""

    def __init__(self, proxies: list[str | None]) -> None:
        """Создаёт ротатор; пустой список заменяется на ``[None]``."""
        self._proxies: list[str | None] = proxies or [None]
        self._idx: int = 0

    @property
    def proxies(self) -> list[str | None]:
        """Полный список прокси пула."""
        return self._proxies

    def next(self) -> str | None:
        """Возвращает следующий прокси по кругу."""
        proxy = self._proxies[self._idx % len(self._proxies)]
        self._idx += 1
        return proxy


def load_rotator() -> ProxyRotator:
    """Собирает ротатор из загруженного пула прокси."""
    return ProxyRotator(load_proxies())
