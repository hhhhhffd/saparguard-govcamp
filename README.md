# SaparGuard

SaparGuard сохраняет сырые сообщения выбранных Telegram-групп и каналов в PostgreSQL.
Он обрабатывает изображения и распознаёт номера, но на текущем этапе **не** выполняет extraction,
ML-анализ сообщений, risk scoring, граф связей, карту или продуктовый dashboard.

API и Jinja Web UI работают в FastAPI, а collector — отдельный Telethon-процесс. Media worker
запускается только внутри collector-процесса и получает уже авторизованный `TelegramClient`; второй
процесс с тем же session-файлом не создаётся.

## Требования

- Python 3.12;
- PostgreSQL;
- Node.js с Corepack — только для локальной сборки frontend assets;
- Docker Compose либо локальные Python/PostgreSQL.

UI пока не содержит аутентификацию. Не выставляйте его публично без reverse proxy authentication
или встроенной авторизации.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
corepack enable
cd web-assets
pnpm install --frozen-lockfile
pnpm build
cd ..
cp .env.example .env
# заполните DATABASE_URL, TELEGRAM_API_ID и TELEGRAM_API_HASH
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
# в другом терминале
.venv/bin/python -m app.collector.service
```

Для разработки CSS в watch-режиме:

```bash
cd web-assets
pnpm dev
```

Все frontend-библиотеки локальны: HTMX 2.0.10, Alpine CSP 3.15.12 и Tailwind 4.3.2. Node.js и
`node_modules` отсутствуют в runtime Docker image. См. [frontend stack](docs/frontend-stack.md).

## Docker / production

```bash
cp .env.example .env
# заполните TELEGRAM_API_ID и TELEGRAM_API_HASH
docker compose up --build
```

Откройте `http://localhost:8000`. При первой авторизации collector должен работать в интерактивном
терминале, чтобы создать Telethon session; затем session хранится в Docker volume `telethon_data`.

Non-Docker deploy создаёт bundle с уже собранными static assets:

```bash
./scripts/prepare_deploy.sh
scp -r deploy user@vps:~/
ssh user@vps 'cd ~/deploy && sudo bash scripts/install.sh'
```

`install.sh` не устанавливает Node.js: он проверяет, что bundle содержит построенные CSS, HTMX,
Alpine CSP и application JavaScript. Скрипт не удаляет существующие PostgreSQL данные, Telethon
session, логи или `.env`.

## Routes

- JSON API: `/api/sources`, `/api/messages`, `/api/media`, `/api/stats`, `/api/collector/status`;
- pages: `/`, `/sources`, `/messages`;
- HTMX fragments: `/ui/fragments/...`;
- изменяющие Web actions (POST): `/ui/actions/...`.

Telegram-текст отображается экранированным. Server-rendered Web routes получают CSP без
`unsafe-eval`, `X-Content-Type-Options`, `Referrer-Policy` и защиту от embedding; Swagger `/docs`
не затрагивается этой CSP.

## Media processing boundary

Сейчас worker должен жить рядом с collector, потому что загрузка Telegram-файлов использует его
авторизованный `TelegramClient`. Будущее безопасное разделение: отдельный компонент Telegram media
fetch сохраняет локальный input, а независимый local image processor получает только файл и job ID.
До появления этой границы отдельный Docker/systemd media-worker сервис запрещён.

## Checks

```bash
python -m compileall app alembic
ruff check .
ruff format --check .
pytest
alembic upgrade head
docker compose config
docker compose build
```
