"""Постановка задач на алерт пользователям в Google Cloud Tasks.

Сервис сам резолвит подписчиков/портфели и ставит по одной задаче на
пользователя с готовыми персональными алертами. Воркер бота только
форматирует текст и отправляет в Telegram.
"""

from __future__ import annotations

import asyncio
import logging

from google.cloud import tasks_v2

from .alerts import UserAlertsPayload
from .settings import settings

logger = logging.getLogger(__name__)


def _build_task(body: bytes) -> tasks_v2.Task:
    """Собирает HTTP-задачу к таргету воркера.

    OIDC-токен прикрепляется только для ``https://``-таргета с заданным service
    account: Cloud Tasks запрещает заголовок авторизации на не-HTTPS URL. Для
    ``http://`` (например, локальный/тестовый IP) задача ставится без токена.
    """
    request = tasks_v2.HttpRequest(
        http_method=tasks_v2.HttpMethod.POST,
        url=settings.tasks_target_url,
        headers={"Content-Type": "application/json"},
        body=body,
    )
    use_oidc = (
        settings.tasks_target_url.startswith("https://")
        and bool(settings.tasks_oidc_service_account)
    )
    if use_oidc:
        request.oidc_token = tasks_v2.OidcToken(
            service_account_email=settings.tasks_oidc_service_account,
            audience=settings.tasks_oidc_audience or settings.tasks_target_url,
        )
    return tasks_v2.Task(http_request=request)


def _create_tasks_sync(bodies: list[bytes]) -> list[str]:
    """Синхронно создаёт задачи в очереди и возвращает их имена."""
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(settings.gcp_project, settings.gcp_location, settings.tasks_queue)
    return [client.create_task(parent=parent, task=_build_task(body)).name for body in bodies]


async def enqueue_alerts(payloads: list[UserAlertsPayload]) -> None:
    """Ставит по одной задаче на каждого пользователя с его алертами.

    При ``settings.tasks_dry_run`` только логирует payload (без обращения к GCP).
    """
    if not payloads:
        return

    if settings.tasks_dry_run:
        for payload in payloads:
            logger.info(
                "[dry-run] Задача не отправлена, payload: %s",
                payload.model_dump_json(),
            )
        return

    bodies = [payload.model_dump_json().encode("utf-8") for payload in payloads]
    names = await asyncio.to_thread(_create_tasks_sync, bodies)
    logger.info("Поставлено задач Cloud Tasks: %d", len(names))
