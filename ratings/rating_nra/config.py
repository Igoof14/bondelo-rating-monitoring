"""Конфигурация полинга рейтингов НРА."""

from __future__ import annotations

import os

BASE_URL = "https://www.ra-national.ru"
# WordPress REST endpoint кастомного типа записи «press_release» — надёжный
# источник листинга (страница /ratings/ рендерится через JetEngine AJAX).
REST_PATH = "/wp-json/wp/v2/press_release"

# Сколько страниц листинга проверять за один полл.
MAX_PAGES = int(os.getenv("NRA_MAX_PAGES", "5"))
# Релизов на странице REST-листинга.
PER_PAGE = int(os.getenv("NRA_PER_PAGE", "20"))
# Серия уже известных релизов подряд, после которой полл останавливается
# (фид отсортирован по modified-desc — значит мы «догнали» актуальное).
EARLY_STOP_KNOWN = int(os.getenv("NRA_EARLY_STOP_KNOWN", "10"))

# HTTP
TIMEOUT = int(os.getenv("NRA_TIMEOUT", "30"))
CONCURRENCY = int(os.getenv("NRA_CONCURRENCY", "5"))
