# rating-monitoring

Сервис мониторинга кредитных рейтингов российских агентств (НРА, НКР).

За один запуск сервис:

1. опрашивает сайты агентств (WordPress REST у НРА, HTML-скрейпинг у НКР) через
   пул прокси;
2. дедуплицирует релизы по снимку из таблицы `rating_releases` и **сохраняет**
   новые/изменённые события в БД;
3. ставит **одну** задачу в Google Cloud Tasks со списком изменённых релизов.

Матчинг подписчиков и портфелей, а также отправку сообщений в Telegram выполняет
отдельный воркер (в боте): он принимает задачу, читает детали из той же таблицы
`rating_releases` и рассылает алерты.

Запускается как **Google Cloud Run Job** по расписанию (Cloud Scheduler каждые
N минут): один прогон всех агентств → выход.

## Архитектура

```
main.py → run_all()
  └─ параллельно по агентствам (НРА, НКР):
       get_seen(agency)          # снимок дедупа из БД
       poll(known)               # client → parser → select_changed
       upsert_many(events)       # запись событий в rating_releases
       собрать ReleaseRef[]      # (agency, uid, change_type)
  └─ enqueue_alert(refs)         # ОДНА задача в Cloud Tasks
```

Payload задачи:

```json
{ "releases": [ { "agency": "nra", "uid": "12345", "change_type": "new" } ] }
```

## Структура

| Модуль | Назначение |
|---|---|
| `main.py` | точка входа Job |
| `ratings/settings.py` | конфигурация из окружения (pydantic-settings) |
| `ratings/db.py` | async SQLAlchemy engine + `session_scope` |
| `ratings/cloud_tasks.py` | постановка задачи в Cloud Tasks |
| `ratings/base_service.py` | общий поллер (опрос → дедуп → сохранение) |
| `ratings/selection.py` | отбор новых/изменённых релизов |
| `ratings/repository.py` | доступ к `rating_releases` |
| `ratings/models.py` | ORM-модель `RatingRelease` |
| `ratings/proxy_pool.py` | пул прокси для скрейпинга |
| `ratings/rating_nra/`, `ratings/rating_nkr/` | провайдеры (client/parser/config/service) |

## Переменные окружения

| Переменная | Обязательна | Описание |
|---|---|---|
| `DATABASE_URL` | да | async URL PostgreSQL, напр. `postgresql+asyncpg://user:pass@host:5432/db` |
| `PROXIES` | нет | список прокси (через запятую/пробел/перенос); пусто — прямое соединение |
| `GCP_PROJECT` | да¹ | проект GCP для очереди |
| `GCP_LOCATION` | да¹ | регион очереди Cloud Tasks |
| `TASKS_QUEUE` | да¹ | имя очереди Cloud Tasks |
| `TASKS_TARGET_URL` | да¹ | URL воркера-алертера (HTTP-таргет задачи) |
| `TASKS_OIDC_SERVICE_ACCOUNT` | да¹ | service account для OIDC-токена |
| `TASKS_OIDC_AUDIENCE` | нет | аудитория токена (по умолчанию = target URL) |
| `TASKS_DRY_RUN` | нет | `true` — не отправлять задачу, только залогировать payload |
| `LOG_LEVEL` | нет | уровень логирования (по умолчанию `INFO`) |

¹ Не требуется при `TASKS_DRY_RUN=true` (локальная проверка без GCP).

Скрейпинг настраивается переменными провайдеров (`NRA_*`, `NKR_*`) — см.
`ratings/rating_nra/config.py`, `ratings/rating_nkr/config.py`.

## Локальный запуск

```bash
uv sync
export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db"
export TASKS_DRY_RUN=true          # без реальной очереди
uv run python main.py
```

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
```

## Деплой (Cloud Run Job)

Собрать образ (Python 3.13), задать команду `python main.py`, прокинуть env
(секреты — через Secret Manager) и создать расписание:

```bash
gcloud run jobs deploy rating-monitoring \
  --source . --region "$GCP_LOCATION" \
  --set-secrets DATABASE_URL=rating-db-url:latest \
  --set-env-vars GCP_PROJECT=...,GCP_LOCATION=...,TASKS_QUEUE=...,TASKS_TARGET_URL=...,TASKS_OIDC_SERVICE_ACCOUNT=...

gcloud scheduler jobs create http rating-monitoring-tick \
  --schedule "*/10 * * * *" \
  --uri "https://<region>-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/<project>/jobs/rating-monitoring:run" \
  --oauth-service-account-email <runner-sa>
```
