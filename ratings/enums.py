"""Рейтинговые агентства."""

from __future__ import annotations

from enum import Enum


class RatingAgency(Enum):
    """Рейтинговое агентство.

    Единственный источник правды о наборе агентств. Добавление нового агентства =
    новое значение enum + его скрейпер-провайдер (см. ``AVAILABLE_AGENCIES``).
    """

    NRA = "nra"
    NKR = "nkr"
    ACRA = "acra"

    @property
    def display_name(self) -> str:
        """Человекочитаемое имя агентства."""
        return _DISPLAY_NAMES[self]


_DISPLAY_NAMES = {
    RatingAgency.NRA: "НРА",
    RatingAgency.NKR: "НКР",
    RatingAgency.ACRA: "АКРА",
}


AVAILABLE_AGENCIES: list[RatingAgency] = [
    RatingAgency.NRA,
    RatingAgency.NKR,
    RatingAgency.ACRA,
]
