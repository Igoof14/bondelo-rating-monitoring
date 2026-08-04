"""Парсинг листинга и страниц релизов АКРА (acra-ratings.ru)."""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from ratings.events import RatingEvent, ReleaseStub

from . import config

logger = logging.getLogger(__name__)

# Ссылка на детальную страницу релиза: /press-releases/{id}/
_DETAIL_HREF_RE = re.compile(r"^/press-releases/(\d+)/$")
# ISIN: 2 буквы кода страны + 10 буквенно-цифровых символов.
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")
# ИНН в таблице регуляторного раскрытия. Метка обязательна: рядом может стоять
# «TIN: DMCC189689» иностранного эмитента, его брать нельзя.
_INN_RE = re.compile(r"ИНН[:\s]\s*([0-9]{10,12})")
# Дата ДД.ММ.ГГГГ.
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Название эмитента в кавычках «…».
_QUOTED_RE = re.compile(r"«([^»]+)»")

# Значение рейтинга АКРА. Буквенная часть пишется и латиницей, и кириллицей,
# нередко вперемешку в одном токене («АA-(RU)»), поэтому класс покрывает оба
# алфавита, а результат нормализуется в латиницу. Суффиксы шкал:
# (RU) — национальная, (ru.sf) — структурированное финансирование.
# Префикс «e» (ожидаемый рейтинг) тоже встречается в обоих алфавитах.
_VALUE_RE = re.compile(r"\b([eе]?[ABCDАВСЕ]{1,3}[+\-]?\([Rr][Uu](?:\.sf)?\))")

# Кириллические двойники латинских букв рейтинговой шкалы.
_HOMOGLYPHS = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "е": "e"})

_OUTLOOK_WORDS = {
    "стабильный": "Стабильный",
    "позитивный": "Позитивный",
    "негативный": "Негативный",
    "развивающийся": "Развивающийся",
}
# Корни глаголов рейтингового действия → каноничная метка. Метки совпадают с
# НКР и НРА: по ним бот подбирает формулировки уведомления.
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
    ("УСТАНОВ", "Изменён"),
    ("ПЕРЕСМОТР", "Пересмотр"),
)

# Метки таблицы «Регуляторное раскрытие» → ключи. Сравнение по вхождению
# подстроки в нижнем регистре; порядок задаёт приоритет при совпадении.
_FIELD_MAP = {
    "краткое наименование рейтингуемого лица": "entity_short_name",
    "краткое наименование объекта рейтинга": "object_short_name",
    "полное наименование рейтингуемого лица": "entity_full_name",
    # Последний фолбэк: у релизов по регионам других полей с названием нет.
    # Для выпусков облигаций сюда попадает многословное «Облигации, ООО "…",
    # Старший необеспеченный долг серии: …», поэтому приоритет самый низкий.
    "полное наименование объекта рейтинга": "object_full_name",
    "вид объекта рейтинга": "entity_type",
    "идентификационный номер налогоплательщика": "inn",
}


def parse_listing(html: str) -> list[ReleaseStub]:
    """Извлекает строки листинга в ``ReleaseStub`` (новейшие сверху)."""
    soup = BeautifulSoup(html, "html.parser")
    stubs: list[ReleaseStub] = []
    seen: set[str] = set()

    for row in soup.find_all("div", class_="documents-row"):
        if not isinstance(row, Tag):
            continue
        link = row.find("a", class_="item__title")
        if not isinstance(link, Tag):
            continue
        match = _DETAIL_HREF_RE.match(str(link.get("href") or ""))
        if not match:
            continue
        release_id = match.group(1)
        if release_id in seen:
            continue
        seen.add(release_id)

        emitter = row.find("span", class_="item__emit")
        stubs.append(
            ReleaseStub(
                uid=release_id,
                url=f"{config.BASE_URL}/press-releases/{release_id}/",
                title=link.get_text(" ", strip=True),
                entity_name=emitter.get_text(" ", strip=True) if isinstance(emitter, Tag) else None,
            )
        )
    return stubs


def _normalize_value(value: str) -> str:
    """Нормализует значение рейтинга: кириллические двойники → латиница."""
    return value.translate(_HOMOGLYPHS)


def _extract_action(title: str) -> str | None:
    """Каноничное действие по первому глаголу после «АКРА».

    Берём именно ведущий глагол: в конце заголовка об отзыве встречаются
    слова вроде «подтверждения», которые дали бы ложное «Подтверждён».
    """
    match = re.search(r"АКРА\s+([А-ЯЁа-яё]+)", title)
    if match:
        verb = match.group(1).upper()
        for stem, label in _ACTION_STEMS:
            if stem in verb:
                return label

    upper = title.upper()
    for stem, label in _ACTION_STEMS:
        if stem in upper:
            return label
    return None


def _extract_value(title: str, body: str) -> str | None:
    """Новое значение рейтинга.

    В заголовке актуальное значение всегда последнее («ПОВЫСИЛО … С X ДО Y»),
    поэтому берём последнее совпадение. Если в заголовке шкалы нет (релизы по
    структурированному финансированию), берём первое совпадение в теле — там
    рейтинговое действие описано в лид-абзаце.
    """
    matches = _VALUE_RE.findall(title)
    if matches:
        return _normalize_value(matches[-1])
    match = _VALUE_RE.search(body)
    return _normalize_value(match.group(1)) if match else None


def _extract_outlook(text: str) -> str | None:
    """Прогноз по слову в кавычках («Стабильный», «Позитивный», …)."""
    lowered = text.lower()
    for word, canonical in _OUTLOOK_WORDS.items():
        if f"«{word}»" in lowered:
            return canonical
    return None


def _parse_disclosure(content: Tag) -> dict[str, str]:
    """Извлекает пары метка-значение из таблиц регуляторного раскрытия."""
    fields: dict[str, str] = {}
    for tr in content.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).lower()
        value = cells[1].get_text(" ", strip=True)
        for key_part, attr in _FIELD_MAP.items():
            if key_part in label and attr not in fields:
                fields[attr] = value
                break
    return fields


def _extract_isins(*texts: str) -> list[str]:
    """Собирает ISIN из переданных текстов, сохраняя порядок и без повторов."""
    isins: list[str] = []
    for text in texts:
        for isin in _ISIN_RE.findall(text):
            if isin not in isins:
                isins.append(isin)
    return isins


def _extract_publication_date(soup: BeautifulSoup, content_text: str) -> date | None:
    """Дата публикации из ``time.publication_date`` либо из текста страницы."""
    time_el = soup.find("time", class_="publication_date")
    raw = str(time_el.get("datetime") or "") if isinstance(time_el, Tag) else ""
    for source in (raw, content_text):
        match = _DATE_RE.search(source)
        if not match:
            continue
        day, month, year = (int(group) for group in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _clean_name(value: str | None) -> str | None:
    """Схлопывает пробелы (в разметке АКРА много ``&nbsp;``); пустое → ``None``."""
    if not value:
        return None
    collapsed = " ".join(value.replace("\xa0", " ").split())
    return collapsed or None


def _extract_entity_name(stub: ReleaseStub, fields: dict[str, str], title: str) -> str | None:
    """Имя эмитента: листинг → названия из раскрытия → кавычки заголовка."""
    for candidate in (
        stub.entity_name,
        fields.get("entity_short_name"),
        fields.get("object_short_name"),
        fields.get("entity_full_name"),
    ):
        cleaned = _clean_name(candidate)
        if cleaned:
            return cleaned

    # В кавычках «…» в заголовке стоит не только имя эмитента, но и прогноз
    # («ПРОГНОЗ «СТАБИЛЬНЫЙ»») — его в имя пропускать нельзя.
    for quoted in _QUOTED_RE.findall(title):
        cleaned = _clean_name(quoted)
        if cleaned and cleaned.lower() not in _OUTLOOK_WORDS:
            return cleaned

    return _clean_name(fields.get("object_full_name"))


def parse_release(html: str, stub: ReleaseStub) -> RatingEvent | None:
    """Парсит страницу релиза АКРА и собирает ``RatingEvent``.

    Действие/значение/прогноз берутся из заголовка (он формализован), ИНН,
    вид объекта и наименования — из таблицы регуляторного раскрытия. Парсинг
    ограничен основным блоком: сайдбар ``.aside`` содержит связанные релизы,
    чужие ISIN из них попадать в событие не должны.
    """
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.find("h1", class_="page-caption")
    title = heading.get_text(" ", strip=True) if isinstance(heading, Tag) else stub.title

    content = soup.find("div", class_="current-document__inner-content")
    if not isinstance(content, Tag):
        logger.warning(f"Не найден основной блок релиза {stub.url}")
        return None
    content_text = content.get_text(" ", strip=True)

    fields = _parse_disclosure(content)
    rating_action = _extract_action(title)

    # У релизов об отзыве действующего значения и прогноза нет: и то и другое
    # ещё встречается в теле как история, но событию не принадлежит.
    if rating_action == "Отозван":
        rating_value = None
        outlook = None
    else:
        rating_value = _extract_value(title, content_text)
        outlook = _extract_outlook(title) or _extract_outlook(content_text)

    inn_match = _INN_RE.search(fields.get("inn", "")) or _INN_RE.search(content_text)

    try:
        return RatingEvent(
            uid=stub.uid,
            url=stub.url,
            release_id=stub.uid,
            entity_name=_extract_entity_name(stub, fields, title),
            entity_type=fields.get("entity_type"),
            inn=inn_match.group(1) if inn_match else None,
            isins=_extract_isins(title, content_text),
            rating_action=rating_action,
            rating_value=rating_value,
            outlook=outlook,
            publication_date=_extract_publication_date(soup, content_text),
        )
    except Exception as e:
        logger.error(f"Не удалось собрать RatingEvent для {stub.url}: {e}")
        return None
