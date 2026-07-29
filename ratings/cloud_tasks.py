"""Постановка задач на алерт пользователям в Google Cloud Tasks.

Сервис сам резолвит подписчиков/портфели и ставит по одной задаче на
пользователя с готовыми персональными алертами. Воркер бота только
форматирует текст и отправляет в Telegram.

Имя задачи детерминировано (rating-{scope}-{telegram_id}-{yyyymmddHHMM}) — при
ретрае Cloud Run Job дубликат отбрасывается как AlreadyExists, иначе получатели
увидели бы один и тот же релиз дважды. Аудитория входит в имя, чтобы задачи не
схлопнулись, если пользователь сменил режим между прогонами.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from .alerts import AlertScope, UserAlertsPayload
from .settings import settings

logger = logging.getLogger(__name__)


def _build_task(
    client: tasks_v2.CloudTasksClient,
    payload: UserAlertsPayload,
    body: bytes,
    run_suffix: str,
) -> tasks_v2.Task:
    """Собирает HTTP-задачу к таргету воркера.

    OIDC-токен прикрепляется только для ``https://``-таргета с заданным service
    account: Cloud Tasks запрещает заголовок авторизации на не-HTTPS URL. Для
    ``http://`` (например, локальный/тестовый IP) задача ставится без токена.

    Задачам рыночной аудитории проставляется ``schedule_time`` со сдвигом:
    подписчики с портфелем должны получить алерт первыми.
    """
    request = tasks_v2.HttpRequest(
        http_method=tasks_v2.HttpMethod.POST,
        url=settings.alert_target_url,
        headers={"Content-Type": "application/json"},
        body=body,
    )
    use_oidc = (
        settings.alert_target_url.startswith("https://")
        and bool(settings.alert_task_sa_email)
    )
    if use_oidc:
        request.oidc_token = tasks_v2.OidcToken(
            service_account_email=settings.alert_task_sa_email,
            audience=settings.alert_token_audience or settings.alert_target_url,
        )

    task = tasks_v2.Task(
        name=client.task_path(
            settings.gcp_project_id,
            settings.cloud_tasks_location,
            settings.cloud_tasks_queue,
            f"rating-{payload.scope.value}-{payload.telegram_id}-{run_suffix}",
        ),
        http_request=request,
    )

    if payload.scope is AlertScope.MARKET and settings.bulk_delay_seconds:
        schedule_time = timestamp_pb2.Timestamp()
        schedule_time.FromDatetime(
            datetime.now(UTC) + timedelta(seconds=settings.bulk_delay_seconds)
        )
        task.schedule_time = schedule_time

    return task


def _create_tasks_sync(payloads: list[UserAlertsPayload], run_suffix: str) -> int:
    """Синхронно создаёт задачи в очереди, возвращает количество поставленных.

    Сбой по одному получателю не должен обрывать рассылку остальным.
    """
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(
        settings.gcp_project_id,
        settings.cloud_tasks_location,
        settings.cloud_tasks_queue,
    )

    created = 0
    for payload in payloads:
        body = payload.model_dump_json().encode("utf-8")
        try:
            client.create_task(
                parent=parent, task=_build_task(client, payload, body, run_suffix)
            )
        except AlreadyExists:
            logger.info(
                "Задача пользователю %s уже в очереди (ретрай джоба)",
                payload.telegram_id,
            )
        except Exception:
            logger.exception(
                "Ошибка постановки задачи пользователю %s", payload.telegram_id
            )
            continue
        created += 1
    return created


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

    run_suffix = datetime.now(UTC).strftime("%Y%m%d%H%M")
    created = await asyncio.to_thread(_create_tasks_sync, payloads, run_suffix)
    logger.info("Поставлено задач Cloud Tasks: %d", created)
