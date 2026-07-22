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
    gcp_project: str = "bond-invest"
    gcp_location: str = "europe-west3"
    tasks_queue: str = "bot-alert-tasks"
    tasks_target_url: str = "http://34.178.57.246:8080/notify"
    # Service account для OIDC-токена запроса к таргету.
    tasks_oidc_service_account: str = "cloud-tasks-invoker@bond-invest.iam.gserviceaccount.com"
    # Аудитория OIDC-токена; по умолчанию совпадает с target URL.
    tasks_oidc_audience: str = ""
    # Не отправлять задачу, только залогировать payload (для локальной проверки).
    tasks_dry_run: bool = False

    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
"""Синглтон настроек сервиса (обязательные поля читаются из окружения)."""
