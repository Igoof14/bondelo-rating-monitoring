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

    # --- База данных (PostgreSQL на стороннем сервере) ---
    # SQLAlchemy async URL, например: postgresql+asyncpg://user:pass@host:5432/db
    database_url: str

    # --- Прокси для скрейпинга (используются proxy_pool) ---
    # Список прокси (через запятую/пробел/перенос) либо один прокси.
    ratings_proxies: str | None = None
    ratings_proxy: str | None = None

    # --- Google Cloud Tasks ---
    # Реквизиты очереди и HTTP-таргета воркера-алертера (в боте).
    gcp_project: str = ""
    gcp_location: str = ""
    tasks_queue: str = ""
    tasks_target_url: str = ""
    # Service account для OIDC-токена запроса к таргету.
    tasks_oidc_service_account: str = ""
    # Аудитория OIDC-токена; по умолчанию совпадает с target URL.
    tasks_oidc_audience: str = ""
    # Не отправлять задачу, только залогировать payload (для локальной проверки).
    tasks_dry_run: bool = False

    # --- Логирование ---
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
"""Синглтон настроек сервиса (обязательные поля читаются из окружения)."""
