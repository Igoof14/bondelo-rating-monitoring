"""Парсинг листинга и страниц релизов «Эксперт РА» (raexpert.ru)."""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from ratings.events import RatingEvent, ReleaseStub

from . import config

logger = logging.getLogger(__name__)

# Ссылка на страницу релиза: /releases/{год}/{слаг}, например /releases/2026/aug03b.
_DETAIL_HREF_RE = re.compile(r"^/releases/(\d{4}/[a-z0-9]+)/?$")
# ISIN: 2 буквы кода страны + 10 буквенно-цифровых символов.
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")
# ИНН: в раскрытии у регионов вместо номера стоит «Отсутствует».
_INN_RE = re.compile(r"\b([0-9]{10,12})\b")
# Дата ДД.ММ.ГГГГ.
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Кириллица: по ней отличаем значение рейтинга («ruA+») от слова («отозван»).
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")

# Значение по шкале «Эксперт РА»: ru + 1–3 буквы + модификатор, суффикс шкалы
# структурированного финансирования (.sf) и метка ожидаемого рейтинга (EXP),
# которая в заголовке пишется через пробел: «ruAAА (EXP)».
_VALUE_RE = re.compile(
    r"\b(ru[ABCDАВСЕ]{1,3}[+\-]?(?:\.sf)?(?:\s*\(EXP\))?)",
    re.IGNORECASE,
)
# Кириллические двойники латинских букв рейтинговой шкалы: в заголовках релизов
# «Эксперт РА» они вперемешку с латиницей («ruА+», «ruAAА (EXP)»).
_HOMOGLYPHS = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "е": "e"})

# Прогноз в теле релиза: «Прогноз по рейтингу – стабильный», «прогноз по
# рейтингу стабильный», «изменил прогноз на стабильный» и обратный порядок
# «со стабильным прогнозом». Кавычек, в отличие от АКРА, нет.
_OUTLOOK_STEMS = {
    "стабильн": "Стабильный",
    "позитивн": "Позитивный",
    "негативн": "Негативный",
    "развивающ": "Развивающийся",
}
_OUTLOOK_AFTER_RE = re.compile(
    r"прогноз[а-яё]*(?:\s+по\s+рейтингу)?\s*(?:на\s+)?[–—\-:]?\s*"
    r"(стабильн|позитивн|негативн|развивающ)",
    re.IGNORECASE,
)
_OUTLOOK_BEFORE_RE = re.compile(
    r"(стабильн|позитивн|негативн|развивающ)[а-яё]*\s+прогноз",
    re.IGNORECASE,
)

# Корни глаголов рейтингового действия → каноничная метка. Метки совпадают с
# АКРА, НКР и НРА: по ним бот подбирает формулировки уведомления.
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
# У релизов по компании заполнено «…объекта рейтинга», у релизов по выпускам —
# «…рейтингуемого лица» (объекты там перечислены в таблицах параметров).
_FIELD_MAP = {
    "сокращенное наименование объекта рейтинга": "object_short_name",
    "сокращенное наименование рейтингуемого лица": "entity_short_name",
    "полное наименование объекта рейтинга": "object_full_name",
    "полное наименование рейтингуемого лица": "entity_full_name",
    "вид объекта рейтинга": "entity_type",
    "идентификационный номер налогоплательщика": "inn",
}


def _clean(value: str | None) -> str | None:
    """Схлопывает пробелы и неразрывные пробелы; пустое → ``None``."""
    if not value:
        return None
    collapsed = " ".join(value.replace("\xa0", " ").split())
    return collapsed or None


def _normalize_value(value: str) -> str | None:
    """Нормализует значение рейтинга: гомоглифы → латиница, «(EXP)» без пробела.

    Возвращает ``None`` для ячеек листинга, где вместо значения стоит слово
    («отозван») или прочерк: у отзыва действующего рейтинга нет.
    """
    cleaned = _clean(value)
    if not cleaned:
        return None
    normalized = cleaned.translate(_HOMOGLYPHS).replace(" (EXP)", "(EXP)")
    if _CYRILLIC_RE.search(normalized) or not normalized[0].isalnum():
        return None
    return normalized


def parse_listing(html: str) -> list[ReleaseStub]:
    """Извлекает строки таблицы рейтингов в ``ReleaseStub`` (новейшие сверху).

    Один релиз покрывает несколько объектов и даёт несколько строк подряд
    (выпуски одного эмитента), поэтому строки схлопываются по слагу релиза:
    ведущей считается первая, самая верхняя.
    """
    soup = BeautifulSoup(html, "html.parser")
    stubs: list[ReleaseStub] = []
    seen: set[str] = set()

    for row in soup.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        cells = row.find_all("td", recursive=False)
        # Объект / Рейтинг / Прогноз / Обновлен. Строки модалки экспорта и
        # прочие таблицы страницы этой формы не имеют и отсеиваются здесь.
        if len(cells) != 4:
            continue

        link = cells[3].find("a")
        if not isinstance(link, Tag):
            continue
        match = _DETAIL_HREF_RE.match(str(link.get("href") or ""))
        if not match:
            continue
        slug = match.group(1)
        if slug in seen:
            continue
        seen.add(slug)

        # В первой колонке — ссылка на карточку объекта: /database/companies/…,
        # /database/securities/bonds/… или /database/regions/….
        object_link = cells[0].find("a")
        stubs.append(
            ReleaseStub(
                uid=slug,
                url=f"{config.BASE_URL}/releases/{slug}",
                title=object_link.get_text(" ", strip=True) if isinstance(object_link, Tag) else "",
                entity_name=_clean(object_link.get_text(" ", strip=True))
                if isinstance(object_link, Tag)
                else None,
                rating_value=_normalize_value(cells[1].get_text(" ", strip=True)),
                outlook=_extract_outlook(cells[2].get_text(" ", strip=True)),
            )
        )
    return stubs


def _extract_action(title: str) -> str | None:
    """Каноничное действие по первому глаголу после «Эксперт РА».

    Берём именно ведущий глагол: в хвосте заголовка встречаются вторые действия
    («…повысил … и изменил прогноз», «…отозвал … и снял статус»), которые
    подменили бы основное.
    """
    match = re.search(r"Эксперт\s+РА»?\s+([А-ЯЁа-яё]+)", title)
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
    """Значение рейтинга из заголовка, фолбэк — тело релиза.

    В заголовке актуальное значение последнее («ПОВЫСИЛ … до уровня X»), в теле
    рейтинговое действие описано в первом абзаце — там берём первое совпадение.
    """
    matches = _VALUE_RE.findall(title)
    if matches:
        return _normalize_value(matches[-1])
    match = _VALUE_RE.search(body)
    return _normalize_value(match.group(1)) if match else None


def _extract_outlook(text: str) -> str | None:
    """Прогноз по корню прилагательного рядом со словом «прогноз».

    Ячейка листинга («Стабильный») тоже разбирается этой функцией: там слово
    стоит без контекста, поэтому сначала пробуем сравнить её целиком.
    """
    cleaned = _clean(text)
    if not cleaned:
        return None

    lowered = cleaned.lower()
    for stem, canonical in _OUTLOOK_STEMS.items():
        if lowered.startswith(stem) and len(lowered) <= len(stem) + 3:
            return canonical

    match = _OUTLOOK_AFTER_RE.search(cleaned) or _OUTLOOK_BEFORE_RE.search(cleaned)
    return _OUTLOOK_STEMS[match.group(1).lower()] if match else None


def _parse_disclosure(content: Tag) -> dict[str, str]:
    """Извлекает пары метка-значение из таблицы «Регуляторное раскрытие»."""
    fields: dict[str, str] = {}
    disclosure = content.find("div", class_="rel_disclosure")
    source = disclosure if isinstance(disclosure, Tag) else content

    for tr in source.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = " ".join(cells[0].get_text(" ", strip=True).lower().split())
        value = cells[1].get_text(" ", strip=True)
        for key_part, attr in _FIELD_MAP.items():
            if key_part in label and attr not in fields:
                fields[attr] = value
                break
    return fields


def _extract_isins(text: str) -> list[str]:
    """Собирает ISIN из текста релиза, сохраняя порядок и без повторов."""
    isins: list[str] = []
    for isin in _ISIN_RE.findall(text):
        if isin not in isins:
            isins.append(isin)
    return isins


def _extract_publication_date(content: Tag) -> date | None:
    """Дата публикации из первого абзаца тела («Москва, 03.08.2026»)."""
    first = content.find("p")
    sources = [first.get_text(" ", strip=True)] if isinstance(first, Tag) else []
    for source in sources:
        match = _DATE_RE.search(source)
        if not match:
            continue
        day, month, year = (int(group) for group in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _extract_entity_name(stub: ReleaseStub, fields: dict[str, str]) -> str | None:
    """Имя эмитента: краткие наименования из раскрытия → полные → листинг.

    Раскрытие приоритетнее листинга: в листинге стоит имя конкретного объекта
    («Облигации ИКС 5 ФИНАНС серии 003P-12»), а релиз по выпускам покрывает
    сразу несколько серий — рейтингуемое лицо описывает событие вернее.
    """
    for candidate in (
        fields.get("object_short_name"),
        fields.get("entity_short_name"),
        fields.get("object_full_name"),
        fields.get("entity_full_name"),
        stub.entity_name,
    ):
        cleaned = _clean(candidate)
        if cleaned:
            return cleaned
    return None


def parse_release(html: str, stub: ReleaseStub) -> RatingEvent | None:
    """Парсит страницу релиза «Эксперт РА» и собирает ``RatingEvent``.

    Значение и прогноз берутся из строки листинга (там они чище: в заголовке
    релиза буквы шкалы вперемешку с кириллицей), действие — из заголовка,
    ИНН/вид объекта/наименования — из таблицы регуляторного раскрытия,
    ISIN — из таблиц параметров выпусков в теле.
    """
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.find("h1")
    title = heading.get_text(" ", strip=True) if isinstance(heading, Tag) else stub.title

    content = soup.find("article", class_="b-article__body")
    if not isinstance(content, Tag):
        logger.warning(f"Не найден основной блок релиза {stub.url}")
        return None
    content_text = content.get_text(" ", strip=True)

    fields = _parse_disclosure(content)
    rating_action = _extract_action(title)

    # У релизов об отзыве действующего значения и прогноза нет: и то и другое
    # ещё встречается в теле как история («Ранее у Компании действовал рейтинг
    # на уровне ruBBB- с развивающимся прогнозом»), но событию не принадлежит.
    if rating_action == "Отозван":
        rating_value = None
        outlook = None
    else:
        rating_value = stub.rating_value or _extract_value(title, content_text)
        outlook = stub.outlook or _extract_outlook(content_text)

    inn_match = _INN_RE.search(fields.get("inn", ""))

    try:
        return RatingEvent(
            uid=stub.uid,
            url=stub.url,
            release_id=stub.uid,
            entity_name=_extract_entity_name(stub, fields),
            entity_type=_clean(fields.get("entity_type")),
            inn=inn_match.group(1) if inn_match else None,
            isins=_extract_isins(content_text),
            rating_action=rating_action,
            rating_value=rating_value,
            outlook=outlook,
            publication_date=_extract_publication_date(content),
        )
    except Exception as e:
        logger.error(f"Не удалось собрать RatingEvent для {stub.url}: {e}")
        return None
