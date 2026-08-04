"""Конфигурация полинга рейтингов «Эксперт РА» (raexpert.ru)."""

from __future__ import annotations

import os

BASE_URL = "https://raexpert.ru"
# Листинга пресс-релизов у «Эксперт РА» нет (/releases/ отдаёт пустую обёртку),
# поэтому источник свежих действий — таблица всех действующих рейтингов,
# отсортированная по колонке «Обновлен» по убыванию. Одна страница — 20 строк.
LIST_PATH = "/ratings/"

# Сколько верхних строк листинга проверять за один полл (новейшие сверху).
# 20 — это вся первая страница; глубже пришлось бы ходить через POST-пагинацию
# с CSRF-токеном и хешем страницы в сессии (см. RA.md).
MAX_ITEMS = int(os.getenv("RA_MAX_ITEMS", "20"))
# Серия уже известных релизов подряд, после которой полл останавливается.
EARLY_STOP_KNOWN = int(os.getenv("RA_EARLY_STOP_KNOWN", "10"))

# HTTP
TIMEOUT = int(os.getenv("RA_TIMEOUT", "30"))
CONCURRENCY = int(os.getenv("RA_CONCURRENCY", "2"))

# Сайт прикрыт QRATOR и ограничивает именно частоту: пачка из 11 страниц с
# concurrency 5 дала 4 успеха и семь 429, те же 11 страниц последовательно с
# паузой 0.5 с — 11/11. Заголовка Retry-After в 429 нет. Берём 1 с с запасом:
# в установившемся режиме за полл забирается 0–3 релиза, пауза не заметна,
# а первый прогон на 11 релизах занимает ~18 с.
REQUEST_INTERVAL = float(os.getenv("RA_REQUEST_INTERVAL", "1.0"))
# Повтор через следующий прокси: 429 привязан к IP, смена адреса помогает
# надёжнее паузы.
RETRIES = int(os.getenv("RA_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RA_RETRY_DELAY", "5.0"))
# Браузерный User-Agent: без него WAF отвечает охотнее отказом.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)
