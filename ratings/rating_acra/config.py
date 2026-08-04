"""Конфигурация полинга рейтингов АКРА (acra-ratings.ru)."""

from __future__ import annotations

import os
from pathlib import Path

BASE_URL = "https://www.acra-ratings.ru"
# Листинг релизов: types[0]=6 — только «Пресс-релиз» (типы 7 «Полный отчет» и
# 11 «Мониторинговый отчет» рейтингового действия не несут). count=30 — максимум,
# который отдаёт сайт на страницу; большие значения молча схлопываются в 30.
LIST_PATH = "/press-releases/?types%5B0%5D=6&count=30"

# Сколько верхних строк листинга проверять за один полл (новейшие сверху).
MAX_ITEMS = int(os.getenv("ACRA_MAX_ITEMS", "30"))
# Серия уже известных релизов подряд, после которой полл останавливается.
EARLY_STOP_KNOWN = int(os.getenv("ACRA_EARLY_STOP_KNOWN", "10"))

# HTTP
TIMEOUT = int(os.getenv("ACRA_TIMEOUT", "30"))
CONCURRENCY = int(os.getenv("ACRA_CONCURRENCY", "5"))
# WAF АКРА отдаёт 503 на серии запросов с одного IP. В проде нагрузка
# размазана по пулу прокси, но на больших пачках (первый прогон) часть страниц
# всё равно отлетает — повторяем через следующий прокси.
RETRIES = int(os.getenv("ACRA_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("ACRA_RETRY_DELAY", "1.5"))
# Bitrix отдаёт HTML только с браузерным User-Agent.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)

# acra-ratings.ru отдаёт только листовой сертификат, без промежуточного
# «GlobalSign RSA OV SSL CA 2018». Браузеры и curl дотягивают его по AIA,
# Python — нет, поэтому проверка цепочки падает с CERTIFICATE_VERIFY_FAILED.
# Промежуточный сертификат лежит рядом и подмешивается в SSL-контекст;
# корень (GlobalSign Root CA - R3) есть в системном хранилище.
# Срок действия — до 21.11.2028, после чего файл нужно обновить.
CA_BUNDLE = Path(__file__).with_name("globalsign_rsa_ov_ssl_ca_2018.pem")
