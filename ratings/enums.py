"""Рейтинговые агентства."""

from __future__ import annotations

from enum import Enum


class RatingAgency(Enum):
    """Рейтинговое агентство.

    Единственный источник правды о наборе агентств. Добавление нового агентства =
    новое значение enum + его скрейпер-провайдер; UI и фильтрация получателей
    подхватывают его автоматически (см. ``AVAILABLE_AGENCIES``).
    """

    NRA = "nra"
    NKR = "nkr"

    @property
    def display_name(self) -> str:
        """Человекочитаемое имя агентства."""
        return _DISPLAY_NAMES[self]


_DISPLAY_NAMES = {
    RatingAgency.NRA: "НРА",
    RatingAgency.NKR: "НКР",
}

# Агентства, по которым уже есть скрейпер и можно получать уведомления.
# UI рисует тумблер на каждое из них. По мере добавления провайдеров —
# дополняем список.
AVAILABLE_AGENCIES: list[RatingAgency] = [
    RatingAgency.NRA,
    RatingAgency.NKR,
]
