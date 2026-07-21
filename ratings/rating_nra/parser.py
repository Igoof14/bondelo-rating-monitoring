"""Парсинг HTML-страницы релиза рейтинга НРА в ``RatingEvent``."""

from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ratings.events import RatingEvent, ReleaseStub

logger = logging.getLogger(__name__)

# Сопоставление русских меток таблицы «ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ» с полями.
# Сравнение по вхождению подстроки (в нижнем регистре).
_FIELD_MAP = {
    "полное наименование объекта рейтинга": "entity_full_name",
    "сокращенное наименование объекта рейтинга": "entity_short_name",
    "вид объекта рейтинга": "entity_type",
    "идентификационный номер налогоплательщика": "inn",
    "isin": "isin",
    "рейтинговое действие": "rating_action",
    "дата публикации": "publication_date",
}

_DATE_RE = re.compile(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})")
_RATING_RE = re.compile(r"\b([A-D][A-D+\-]{0,4}\|ru\|)", re.IGNORECASE)
# ISIN: 2 буквы кода страны + 10 буквенно-цифровых символов.
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")
_OUTLOOK_WORDS = {
    "стабильный": "Стабильный",
    "позитивный": "Позитивный",
    "негативный": "Негативный",
    "развивающийся": "Развивающийся",
}
_NA_VALUES = {"не применимо", "н/д", "—", "-", ""}
# Корни слов рейтингового действия → каноничная метка. НРА использует и
# глагольные формы («повысило»), и причастия («повышен») — корня достаточно.
# Порядок задаёт приоритет при совпадении нескольких корней.
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


def _clean(value: str | None) -> str | None:
    """Возвращает обрезанную строку или ``None`` для пустых/«н/д» значений."""
    if value is None:
        return None
    value = value.strip()
    return None if value.lower() in _NA_VALUES else value


def _parse_isins(raw: str | None) -> list[str]:
    """Извлекает все ISIN из ячейки (релиз может покрывать несколько выпусков)."""
    if not raw:
        return []
    seen: list[str] = []
    for isin in _ISIN_RE.findall(raw.upper()):
        if isin not in seen:
            seen.append(isin)
    return seen


def _parse_date(raw: str | None) -> date | None:
    """Извлекает дату вида ДД.ММ.ГГГГ из строки."""
    if not raw:
        return None
    match = _DATE_RE.search(raw)
    if not match:
        return None
    day, month, year = match.group(1), match.group(2), match.group(3)
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _release_id_from_url(url: str) -> str:
    """Возвращает последний сегмент пути URL как идентификатор релиза."""
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1] or path


def parse_release(html: str, stub: ReleaseStub) -> RatingEvent | None:
    """Парсит страницу релиза НРА и собирает ``RatingEvent``.

    Args:
        html: HTML страницы релиза.
        stub: Листинговая запись (даёт ``post_id``, ``url``, ``modified``).

    Returns:
        ``RatingEvent`` или ``None`` при ошибке парсинга.

    """
    soup = BeautifulSoup(html, "html.parser")

    fields: dict[str, str] = {}
    _parse_info_table(soup, fields)

    rating_action = _extract_action(soup, fields, stub.title)
    rating_value, outlook = _extract_rating_and_outlook(soup)
    if not outlook:
        outlook = _extract_outlook_tab(soup)

    try:
        return RatingEvent(
            uid=stub.uid,
            url=stub.url,
            release_id=_release_id_from_url(stub.url),
            entity_name=_clean(fields.get("entity_short_name"))
            or _clean(fields.get("entity_full_name")),
            entity_type=_clean(fields.get("entity_type")),
            inn=_clean(fields.get("inn")),
            isins=_parse_isins(fields.get("isin")),
            rating_action=rating_action,
            rating_value=rating_value,
            outlook=outlook,
            publication_date=_parse_date(fields.get("publication_date")),
            modified=stub.modified,
        )
    except Exception as e:
        logger.error(f"Не удалось собрать RatingEvent для {stub.url}: {e}")
        return None


def _parse_info_table(soup: BeautifulSoup, out: dict[str, str]) -> None:
    """Извлекает пары ключ-значение из таблицы доп. информации."""
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            label = tds[0].get_text(" ", strip=True).lower()
            value = tds[1].get_text("\n", strip=True)
            for key_part, attr in _FIELD_MAP.items():
                if key_part in label:
                    out[attr] = value
                    break


def _extract_action(soup: BeautifulSoup, fields: dict[str, str], title: str) -> str | None:
    """Определяет каноничное рейтинговое действие по корню слова.

    Источники по приоритету: заголовок релиза (REST title), заголовки H1-H3,
    поле «Рейтинговое действие» таблицы.
    """
    sources: list[str] = [title]
    sources += [
        header.get_text(" ", strip=True)
        for header in soup.find_all(["h1", "h2", "h3"])
        if isinstance(header, Tag)
    ]
    field_action = fields.get("rating_action")
    if field_action:
        sources.append(field_action)

    for text in sources:
        upper = text.upper()
        for stem, label in _ACTION_STEMS:
            if stem in upper:
                return label

    return _clean(field_action)


def _extract_rating_and_outlook(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Извлекает значение рейтинга и прогноз из блока «РЕЗЮМЕ»."""
    resume_text = _find_resume_text(soup)
    if not resume_text:
        return None, None

    rating_value: str | None = None
    match = _RATING_RE.search(resume_text)
    if match:
        rating_value = match.group(1)

    outlook: str | None = None
    lowered = resume_text.lower()
    for word, canonical in _OUTLOOK_WORDS.items():
        if f"«{word}»" in lowered or f'"{word}"' in lowered:
            outlook = canonical
            break

    return rating_value, outlook


def _find_resume_text(soup: BeautifulSoup) -> str | None:
    """Возвращает текст блока «РЕЗЮМЕ» или первого ``span.sample01``."""
    for section in soup.find_all("section", class_="tab"):
        if not isinstance(section, Tag):
            continue
        heading = section.find_previous("span", class_="no-icon")
        if heading and "РЕЗЮМЕ" in heading.get_text(strip=True).upper():
            return section.get_text(" ", strip=True)

    sample = soup.find("span", class_="sample01")
    if isinstance(sample, Tag):
        return sample.get_text(" ", strip=True)
    return None


def _extract_outlook_tab(soup: BeautifulSoup) -> str | None:
    """Ищет прогноз во вкладке «ПРОГНОЗ», если его не было в резюме."""
    for section in soup.find_all("section", class_="tab"):
        if not isinstance(section, Tag):
            continue
        heading = section.find_previous("span", class_="no-icon")
        if heading and "ПРОГНОЗ" in heading.get_text(strip=True).upper():
            text = section.get_text(" ", strip=True).lower()
            for word, canonical in _OUTLOOK_WORDS.items():
                if word in text:
                    return canonical
            if "без прогноза" in text:
                return "Без прогноза"
    return None
