"""Постановка задачи на алерт пользователям в Google Cloud Tasks.

Сервис только детектит изменения рейтингов и кладёт лёгкую задачу со списком
идентификаторов релизов. Резолв подписчиков/портфелей и отправку в Telegram
выполняет воркер на стороне бота, читая детали из той же таблицы
``rating_releases``.
"""

from __future__ import annotations

import asyncio
import json
import logging

from google.cloud import tasks_v2
from pydantic import BaseModel

from .settings import settings

logger = logging.getLogger(__name__)


class ReleaseRef(BaseModel):
    """Ссылка на изменённый релиз для передачи воркеру-алертеру."""

    agency: str
    uid: str
    change_type: str


def _build_task(body: bytes) -> tasks_v2.Task:
    """Собирает HTTP-задачу с OIDC-аутентификацией к таргету воркера."""
    audience = settings.tasks_oidc_audience or settings.tasks_target_url
    return tasks_v2.Task(
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=settings.tasks_target_url,
            headers={"Content-Type": "application/json"},
            body=body,
            oidc_token=tasks_v2.OidcToken(
                service_account_email=settings.tasks_oidc_service_account,
                audience=audience,
            ),
        ),
    )


def _create_task_sync(body: bytes) -> str:
    """Синхронно создаёт задачу в очереди и возвращает её имя."""
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(settings.gcp_project, settings.gcp_location, settings.tasks_queue)
    response = client.create_task(parent=parent, task=_build_task(body))
    return response.name


async def enqueue_alert(releases: list[ReleaseRef]) -> None:
    """Ставит одну задачу со списком изменённых релизов.

    При ``settings.tasks_dry_run`` только логирует payload (без обращения к GCP).
    """
    if not releases:
        return

    payload = {"releases": [r.model_dump() for r in releases]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if settings.tasks_dry_run:
        logger.info("[dry-run] Задача не отправлена, payload: %s", payload)
        return

    name = await asyncio.to_thread(_create_task_sync, body)
    logger.info("Поставлена задача Cloud Tasks (%d релизов): %s", len(releases), name)
