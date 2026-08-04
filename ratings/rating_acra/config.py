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

# WAF АКРА ограничивает частоту запросов: после ~20 подряд начинает отдавать
# 503 и 403. Замеры: 30 страниц пачкой — 10 отказов; те же 30 с паузой 3 с —
# ни одного. Ни браузерные заголовки, ни снижение параллельности не помогают,
# помогает только темп, поэтому запросы идут через общий троттл, а CONCURRENCY
# фактически перестаёт быть ограничителем.
# В установившемся режиме за полл забирается 0–3 новых релиза, так что пауза
# ничего не стоит; ощутимо она влияет только на первый прогон (~95 с на 30
# релизов).
REQUEST_INTERVAL = float(os.getenv("ACRA_REQUEST_INTERVAL", "3.0"))
# Повтор через следующий прокси. 503 означает «сбавь темп», поэтому пауза
# между попытками заметно больше обычного интервала.
RETRIES = int(os.getenv("ACRA_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("ACRA_RETRY_DELAY", "6.0"))
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
