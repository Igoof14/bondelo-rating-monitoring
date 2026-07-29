"""Конфигурация сервиса мониторинга рейтингов.

Единая точка чтения окружения (замена монорепного ``core.config``). Значения
берутся из переменных окружения / ``.env`` / Secret Manager при деплое.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки сервиса, читаемые из окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str

    proxies: str | None = None

    # --- Google Cloud Tasks ---
    # Реквизиты очереди и HTTP-таргета воркера-алертера (в боте).
    gcp_project_id: str = "bond-invest"
    cloud_tasks_location: str = "europe-west3"
    cloud_tasks_queue: str = "bot-alerts"
    alert_target_url: str = "https://bot-772435034855.europe-west3.run.app/events/rating-change"
    # Service account для OIDC-токена запроса к таргету.
    alert_task_sa_email: str = "cloud-tasks-invoker@bond-invest.iam.gserviceaccount.com"
    # Аудитория OIDC-токена; по умолчанию совпадает с target URL.
    alert_token_audience: str = "https://bot-772435034855.europe-west3.run.app"
    # Не отправлять задачу, только залогировать payload (для локальной проверки).
    tasks_dry_run: bool = False
    # Задержка доставки для аудитории без токена: подписчики с подключённым
    # портфелем должны получить алерт первыми.
    bulk_delay_seconds: int = 60

    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
"""Синглтон настроек сервиса (обязательные поля читаются из окружения)."""
