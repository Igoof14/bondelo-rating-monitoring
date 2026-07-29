"""Схемы алертов и матчинг рейтинговых событий на получателей.

Вся бизнес-логика резолва получателей живёт здесь: сервис сам вычисляет, кому
и по каким бумагам относится релиз, и отдаёт боту готовый персональный payload.

Аудитории две. У пользователя с токеном есть портфель, и релиз доезжает,
только если задевает его бумаги. У пользователя без токена портфеля нет — ему
уходят все релизы агентств, на которые он подписан.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from .enums import RatingAgency
from .events import RatingEvent


class AlertScope(StrEnum):
    """Аудитория, которой адресован алерт.

    Уезжает в payload — бот по нему подбирает формулировки.
    """

    PORTFOLIO = "portfolio"
    MARKET = "market"


class MatchedBond(BaseModel):
    """Бумага портфеля, затронутая релизом."""

    isin: str
    name: str


class PortfolioBond(BaseModel):
    """Бумага портфеля пользователя с ИНН эмитента (для матчинга)."""

    isin: str
    name: str
    emitter_inn: str | None = None


class EventPayload(BaseModel):
    """Данные релиза, необходимые боту для текста уведомления."""

    entity_name: str | None
    url: str
    rating_action: str | None
    rating_value: str | None
    outlook: str | None

    @classmethod
    def from_event(cls, event: RatingEvent) -> EventPayload:
        """Собирает payload из доменного события."""
        return cls(
            entity_name=event.entity_name,
            url=event.url,
            rating_action=event.rating_action,
            rating_value=event.rating_value,
            outlook=event.outlook,
        )


class AlertItem(BaseModel):
    """Один алерт пользователя: релиз + затронутые бумаги его портфеля."""

    event: EventPayload
    matched_bond_names: list[MatchedBond]


class UserAlertsPayload(BaseModel):
    """Payload задачи Cloud Tasks: все алерты одного пользователя за прогон."""

    telegram_id: int
    alerts: list[AlertItem]
    scope: AlertScope = AlertScope.PORTFOLIO


def _match_bonds(event: RatingEvent, bonds: list[PortfolioBond]) -> list[MatchedBond]:
    """Возвращает бумаги портфеля, затронутые релизом.

    Бумага матчится, если её ISIN входит в выпуски релиза или ИНН её эмитента
    совпадает с ИНН из релиза.
    """
    release_isins = set(event.isins)
    matched = [
        bond
        for bond in bonds
        if bond.isin in release_isins or (event.inn is not None and bond.emitter_inn == event.inn)
    ]
    return [MatchedBond(isin=bond.isin, name=bond.name) for bond in matched]


def build_user_alerts(
    events_by_agency: dict[RatingAgency, list[RatingEvent]],
    subscriptions: dict[int, set[RatingAgency]],
    portfolios: dict[int, list[PortfolioBond]],
    global_subscribers: set[int] | None = None,
) -> list[UserAlertsPayload]:
    """Матчит события на получателей и собирает персональные payload'ы.

    Пользователь с портфелем получает алерт по релизу, если подписан на
    агентство релиза и в его портфеле есть бумага затронутого
    эмитента/выпуска. Пользователь из ``global_subscribers`` портфеля не
    имеет и получает все релизы своих агентств.

    Портфельные payload'ы идут первыми: у них приоритет доставки.
    """
    global_subscribers = global_subscribers or set()
    payloads: list[UserAlertsPayload] = []

    for telegram_id, agencies in subscriptions.items():
        bonds = portfolios.get(telegram_id)
        if not bonds:
            continue

        alerts: list[AlertItem] = []
        for agency in agencies:
            for event in events_by_agency.get(agency, []):
                matched = _match_bonds(event, bonds)
                if matched:
                    alerts.append(
                        AlertItem(event=EventPayload.from_event(event), matched_bond_names=matched)
                    )

        if alerts:
            payloads.append(UserAlertsPayload(telegram_id=telegram_id, alerts=alerts))

    for telegram_id in sorted(global_subscribers):
        alerts = [
            # Бумаг у получателя нет — бот отрисует релиз по эмитенту.
            AlertItem(event=EventPayload.from_event(event), matched_bond_names=[])
            for agency in subscriptions.get(telegram_id, set())
            for event in events_by_agency.get(agency, [])
        ]
        if alerts:
            payloads.append(
                UserAlertsPayload(
                    telegram_id=telegram_id, alerts=alerts, scope=AlertScope.MARKET
                )
            )

    return payloads
