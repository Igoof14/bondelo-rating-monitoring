"""Конфигурация полинга рейтингов НКР (ratings.ru)."""

from __future__ import annotations

import os

BASE_URL = "https://ratings.ru"
# Листинг пресс-релизов (одна страница, новейшие сверху).
LIST_PATH = "/ratings/press-releases/"

# Сколько верхних строк листинга проверять за один полл (новейшие сверху).
MAX_ITEMS = int(os.getenv("NKR_MAX_ITEMS", "40"))
# Серия уже известных релизов подряд, после которой полл останавливается.
EARLY_STOP_KNOWN = int(os.getenv("NKR_EARLY_STOP_KNOWN", "10"))

# HTTP
TIMEOUT = int(os.getenv("NKR_TIMEOUT", "30"))
CONCURRENCY = int(os.getenv("NKR_CONCURRENCY", "5"))
# Bitrix отдаёт HTML только с браузерным User-Agent.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)
