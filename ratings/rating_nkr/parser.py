"""Парсинг листинга и страниц релизов НКР (ratings.ru)."""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from ratings.events import RatingEvent, ReleaseStub

from . import config

logger = logging.getLogger(__name__)

# Ссылка на детальную страницу релиза: /ratings/press-releases/{slug}/
_DETAIL_HREF_RE = re.compile(r"^/ratings/press-releases/([^/]+)/$")
# Шкала НКР: AAA.ru, AA.ru, A+.ru, BBB-.ru …
_VALUE_RE = re.compile(r"([A-D][A-D+\-]{0,4}\.ru)")
# ISIN: 2 буквы кода страны + 10 буквенно-цифровых символов.
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")
# Основной (левый) блок релиза НКР; сайдбар «похожие» сюда не входит.
_MAIN_CLASS_RE = re.compile(r"npr-l")
# ИНН рейтингуемого лица из блока на детальной странице.
_INN_RE = re.compile(r"\(ИНН\)\s*рейтингуемого лица\s*([0-9]{10,12})")
# Дата ДД.ММ.ГГГГ.
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Дата из slug: …-DDMMYY.
_SLUG_DATE_RE = re.compile(r"-(\d{2})(\d{2})(\d{2})$")
# Название эмитента в кавычках «…».
_QUOTED_RE = re.compile(r"«([^»]+)»")

_OUTLOOK_WORDS = {
    "стабильный": "Стабильный",
    "позитивн": "Позитивный",
    "негативн": "Негативный",
    "развивающ": "Развивающийся",
}
# Корни глаголов рейтингового действия → каноничная метка.
_ACTION_STEMS = (
    ("ПРИСВО", "Присвоен"),
    ("ПОДТВЕР", "Подтверждён"),
    ("ПОВЫС", "Повышен"),
    ("ПОВЫШ", "Повышен"),
    ("ПОНИЗ", "Понижен"),
    ("ПОНИЖ", "Понижен"),
    ("СНИЗ", "Понижен"),
    ("СНИЖ", "Понижен"),
    ("ОТОЗВ", "Отозван"),
    ("ОТЗЫВ", "Отозван"),
    ("ИЗМЕН", "Изменён"),
    ("ПЕРЕСМОТР", "Пересмотр"),
)


def parse_listing(html: str) -> list[ReleaseStub]:
    """Извлекает строки таблицы листинга в ``ReleaseStub`` (новейшие сверху)."""
    soup = BeautifulSoup(html, "html.parser")
    stubs: list[ReleaseStub] = []
    seen: set[str] = set()

    for link in soup.find_all("a", class_="blue-link"):
        if not isinstance(link, Tag):
            continue
        href = str(link.get("href") or "")
        match = _DETAIL_HREF_RE.match(href)
        if not match:
            continue
        slug = match.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        stubs.append(
            ReleaseStub(
                uid=slug,
                url=f"{config.BASE_URL}{href}",
                title=link.get_text(" ", strip=True),
            )
        )
    return stubs


def _extract_action(title: str) -> str | None:
    """Каноничное действие по первому глаголу после «НКР».

    Берём именно ведущий глагол, иначе слова вроде «без подтверждения» в конце
    заголовка об отзыве дают ложное «Подтверждён».
    """
    match = re.search(r"НКР\s+([А-Яа-яЁё]+)", title)
    verb = match.group(1).upper() if match else ""
    for stem, label in _ACTION_STEMS:
        if stem in verb:
            return label
    return None


def _extract_value(title: str) -> str | None:
    """Новое значение рейтинга (последнее `X.ru` в заголовке)."""
    matches = _VALUE_RE.findall(title)
    return matches[-1] if matches else None


def _extract_outlook(text: str) -> str | None:
    """Прогноз по ключевому слову в тексте."""
    lowered = text.lower()
    for stem, canonical in _OUTLOOK_WORDS.items():
        if stem in lowered:
            return canonical
    return None


def _parse_structure(soup: BeautifulSoup) -> dict[str, str]:
    """Извлекает блок «Структура рейтинга» как словарь {метка: значение}."""
    out: dict[str, str] = {}
    for label_el in soup.find_all("span", class_="npr-r-u-l"):
        if not isinstance(label_el, Tag):
            continue
        value_el = label_el.find_next("span", class_="npr-r-u-r")
        if not isinstance(value_el, Tag):
            continue
        label = label_el.get_text(" ", strip=True).lower()
        if label and label not in out:
            out[label] = value_el.get_text(" ", strip=True)
    return out


def _main_text(soup: BeautifulSoup) -> str:
    """Текст основного блока релиза (без сайдбара «похожие»)."""
    parts = [el.get_text(" ", strip=True) for el in soup.find_all(class_=_MAIN_CLASS_RE)]
    return " ".join(parts) if parts else soup.get_text(" ", strip=True)


def _value_from_cell(cell: str | None) -> str | None:
    """Возвращает рейтинг `X.ru` из ячейки (None, если отозван/пусто)."""
    if not cell:
        return None
    match = _VALUE_RE.search(cell)
    return match.group(1) if match else None


def _extract_entity(title: str) -> str | None:
    """Имя эмитента из кавычек «…», если есть."""
    match = _QUOTED_RE.search(title)
    return match.group(1) if match else None


def _date_from_slug(uid: str) -> date | None:
    """Дата публикации из суффикса slug `-DDMMYY`."""
    match = _SLUG_DATE_RE.search(uid)
    if not match:
        return None
    day, month, yy = (int(g) for g in match.groups())
    try:
        return date(2000 + yy, month, day)
    except ValueError:
        return None


def parse_release(html: str, stub: ReleaseStub) -> RatingEvent | None:
    """Парсит страницу релиза НКР и собирает ``RatingEvent``.

    Действие/значение/прогноз/эмитент берутся из заголовка (он есть в листинге),
    ИНН и ISIN — со страницы релиза.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Сайдбар «похожие релизы» — это ссылки blue-link; убираем их, чтобы их ISIN
    # не попали в событие. ИНН и ISIN берём из основного блока.
    for link in soup.find_all("a", class_="blue-link"):
        link.decompose()
    text = _main_text(soup)
    title = stub.title or text[:300]

    # Значение и прогноз надёжнее всего в блоке «Структура рейтинга»;
    # заголовок — фолбэк. Для отозванных рейтинг/прогноз = None.
    structure = _parse_structure(soup)
    rating_value = _value_from_cell(structure.get("рейтинг")) or _extract_value(title)
    outlook = _extract_outlook(structure.get("прогноз", "")) or _extract_outlook(title)

    inn_match = _INN_RE.search(text)
    isins: list[str] = []
    for isin in _ISIN_RE.findall(text):
        if isin not in isins:
            isins.append(isin)

    # Дата релиза надёжно зашита в slug (-DDMMYY); текст страницы — фолбэк.
    publication_date = _date_from_slug(stub.uid)
    if publication_date is None:
        date_match = _DATE_RE.search(text)
        if date_match:
            day, month, year = (int(g) for g in date_match.groups())
            try:
                publication_date = date(year, month, day)
            except ValueError:
                publication_date = None

    try:
        return RatingEvent(
            uid=stub.uid,
            url=stub.url,
            release_id=stub.uid,
            entity_name=_extract_entity(title),
            inn=inn_match.group(1) if inn_match else None,
            isins=isins,
            rating_action=_extract_action(title),
            rating_value=rating_value,
            outlook=outlook,
            publication_date=publication_date,
        )
    except Exception as e:
        logger.error(f"Не удалось собрать RatingEvent для {stub.url}: {e}")
        return None
