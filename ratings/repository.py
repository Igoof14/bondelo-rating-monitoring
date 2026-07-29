"""Доступ к БД: состояние дедупа релизов + подписки и портфели (таблицы бота)."""

from __future__ import annotations

import logging

from sqlalchemy import select, text

from .alerts import PortfolioBond
from .db import session_scope
from .enums import RatingAgency
from .events import ChangeType, RatingEvent
from .models import RatingRelease

logger = logging.getLogger(__name__)


class RatingReleaseRepository:
    """Состояние дедупа увиденных релизов (общая таблица на провайдеров)."""

    @classmethod
    async def get_seen(cls, agency: RatingAgency) -> dict[str, str | None]:
        """Возвращает снимок ``{uid: modified}`` увиденных релизов агентства."""
        try:
            async with session_scope() as session:
                result = await session.execute(
                    select(RatingRelease.uid, RatingRelease.modified).where(
                        RatingRelease.agency == agency.value
                    )
                )
                return {uid: modified for uid, modified in result.all()}
        except Exception as e:
            logger.error(f"Ошибка при получении снимка релизов {agency.value}: {e}")
            return {}

    @classmethod
    async def upsert_many(cls, agency: RatingAgency, events: list[RatingEvent]) -> None:
        """Создаёт или обновляет релизы агентства по ``uid``."""
        if not events:
            return

        async with session_scope() as session:
            for event in events:
                result = await session.execute(
                    select(RatingRelease).where(
                        RatingRelease.agency == agency.value,
                        RatingRelease.uid == event.uid,
                    )
                )
                release = result.scalar_one_or_none()

                if release is None:
                    release = RatingRelease(agency=agency.value, uid=event.uid)
                    session.add(release)

                release.url = event.url
                release.release_id = event.release_id
                release.inn = event.inn
                release.isins = ", ".join(event.isins) if event.isins else None
                release.entity_name = event.entity_name
                release.entity_type = event.entity_type
                release.rating_action = event.rating_action
                release.rating_value = event.rating_value
                release.outlook = event.outlook
                release.publication_date = event.publication_date
                release.modified = event.modified.isoformat() if event.modified else None

            await session.commit()

    @staticmethod
    def classify(
        uid: str, modified_iso: str | None, known: dict[str, str | None]
    ) -> ChangeType | None:
        """Классифицирует релиз: NEW (неизвестен), CHANGED (modified новее), иначе None."""
        if uid not in known:
            return ChangeType.NEW
        if modified_iso is not None and modified_iso != known[uid]:
            return ChangeType.CHANGED
        return None


class SubscriptionRepository:
    """Подписки на рейтинговые алерты (таблицей владеет бот, здесь read-only)."""

    @classmethod
    async def load_enabled(cls) -> dict[int, set[RatingAgency]]:
        """Возвращает включённые агентства по telegram_id."""
        query = text("""
            SELECT telegram_id, agency
            FROM rating_alert_settings
            WHERE alerts_enabled IS TRUE
        """)
        async with session_scope() as session:
            result = await session.execute(query)
            subscriptions: dict[int, set[RatingAgency]] = {}
            for telegram_id, agency_raw in result:
                try:
                    agency = RatingAgency(agency_raw)
                except ValueError:
                    logger.warning(f"Неизвестное агентство в rating_alert_settings: {agency_raw}")
                    continue
                subscriptions.setdefault(telegram_id, set()).add(agency)
            return subscriptions

    @classmethod
    async def load_global_subscribers(cls) -> set[int]:
        """Подписчики без токена — аудитория «весь рынок».

        Токена нет → нет строк в ``user_bonds`` → матчинг по портфелю их
        отсеивает. Пересечения с портфельной аудиторией нет, поэтому дважды
        алерт не уйдёт.
        """
        query = text("""
            SELECT DISTINCT s.telegram_id
            FROM rating_alert_settings s
            JOIN bot_users u ON u.telegram_id = s.telegram_id
            WHERE s.alerts_enabled IS TRUE
              AND u.is_active IS TRUE
              -- Пустая строка — легаси-маркер отсутствия токена.
              AND COALESCE(u.tinvest_token, '') = ''
        """)
        async with session_scope() as session:
            result = await session.execute(query)
            return {row[0] for row in result}


class PortfolioRepository:
    """Портфели пользователей: user_bonds ⋈ bot_users ⋈ moex_bonds ⋈ moex_emitters."""

    @classmethod
    async def load_portfolios(cls) -> dict[int, list[PortfolioBond]]:
        """Возвращает бумаги портфеля с ИНН эмитента по telegram_id.

        Позиции без ISIN или без пары в moex_bonds пропускаются. Одна бумага
        на нескольких счетах схлопывается в одну.
        """
        query = text("""
            SELECT DISTINCT
                bu.telegram_id,
                mb.isin,
                COALESCE(mb.name, mb.shortname, mb.secid) AS name,
                me.inn
            FROM user_bonds ub
            JOIN bot_users bu ON bu.id = ub.bot_user_id
            JOIN moex_bonds mb ON mb.isin = ub.isin
            LEFT JOIN moex_emitters me ON me.emitter_id = mb.emitter_id
            WHERE ub.isin IS NOT NULL
              AND mb.is_traded IS TRUE
        """)
        async with session_scope() as session:
            result = await session.execute(query)
            portfolios: dict[int, list[PortfolioBond]] = {}
            for telegram_id, isin, name, inn in result:
                portfolios.setdefault(telegram_id, []).append(
                    PortfolioBond(isin=isin, name=name, emitter_inn=inn)
                )
            return portfolios
