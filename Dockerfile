# Cloud Run Job: опросить агентства → записать в БД → поставить задачу → выйти.
# Базовый образ с предустановленным uv и Python 3.13.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Байткод-компиляция ускоряет холодный старт; copy-режим — для смонтированного кэша.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Слой зависимостей: ставится из lock-файла и кэшируется, пока не менялись
# pyproject.toml/uv.lock. Сам проект — не пакет, поэтому --no-install-project.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Исходники приложения (venv из образа не затирается — исключён в .dockerignore).
COPY . /app

# Запуск из WORKDIR: cwd на sys.path, поэтому `import ratings` работает.
ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["python", "main.py"]
