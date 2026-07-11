# SaparGuard Telegram Collector

Сервис сохраняет сырые сообщения выбранных Telegram-групп и каналов в PostgreSQL. На этом этапе он не выполняет AI-анализ, не скачивает медиа и не принимает автоматических решений.

Компоненты разделены: `api` отвечает за FastAPI и Web UI, а `collector` — независимый Telethon-процесс. Поэтому просмотр уже записанных данных продолжает работать при остановленном collector.

## Возможности

- пользовательская Telethon-сессия в отдельном локальном файле;
- источники по публичному username или числовому ID, управляемые через UI/API;
- первичная история с лимитом, датой начала и сохранением прогресса;
- новые, отредактированные и удалённые сообщения;
- UPSERT по `(telegram_chat_id, telegram_message_id)`;
- исходные доступные Telethon-метаданные в `JSONB`;
- мягкое удаление источника: сообщения остаются в БД;
- API, UI, Docker Compose, Alembic и systemd-установка.

## Быстрый старт в Docker

```bash
cp .env.example .env
# заполните TELEGRAM_API_ID и TELEGRAM_API_HASH
docker compose up --build
```

Откройте `http://localhost:8000`. Добавьте источник через страницу «Источники». При первом запуске collector Telethon запросит авторизацию в интерактивном терминале; после неё session-файл будет храниться в Docker volume `telethon_data`.

## Локальный запуск без Docker

Нужны Python 3.11+ и PostgreSQL.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# заполните DATABASE_URL и Telegram credentials
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
# в другом терминале
.venv/bin/python -m app.collector.service
```

## API

- `GET/POST /api/sources` — список и добавление источников;
- `POST /api/sources/{id}/enable`, `/disable`, `/history` — управление источником и историей;
- `DELETE /api/sources/{id}` — убрать источник из конфигурации, не затрагивая сообщения;
- `GET /api/messages` — поиск, фильтры, пагинация;
- `GET /api/messages/{id}` — полная карточка и `raw_data`;
- `GET /api/stats`, `GET /api/collector/status` — состояние и ошибки.

## Числовые Telegram ID

Telegram разрешает доступ по числовому ID только к чатам, доступным авторизованному аккаунту. Убедитесь, что этот пользователь уже состоит в группе/подписан на канал. Для незнакомого приватного чата одного ID недостаточно — Telegram также требует access hash; используйте публичный username или откройте чат этим аккаунтом до добавления.

## Deploy на VPS без Docker

Поддерживаются Debian и Ubuntu. Первый скрипт запускается локально и создаёт переносимый каталог. Он автоматически копирует `.env`, если файл существует, но никогда не копирует Telethon session, логи и данные.

```bash
./scripts/prepare_deploy.sh
scp -r deploy user@vps:~/
ssh user@vps
cd ~/deploy
sudo bash scripts/install.sh
```

`install.sh` безопасно использует уже установленный PostgreSQL и не удаляет данные. Если `DATABASE_URL` отсутствует в `.env`, скрипт создаст роль и БД `saparguard`, сгенерирует пароль и добавит URL. Скрипт также применяет миграции, ставит зависимости, проверяет порт API, создаёт systemd-сервисы и запускает API.

После заполнения Telegram credentials на VPS нужно единожды создать пользовательскую сессию в интерактивном терминале:

```bash
sudo -u saparguard -H bash -c 'cd /opt/saparguard && .venv/bin/python -m app.collector.service'
```

Введите телефон, код и пароль 2FA (если включён), затем остановите процесс `Ctrl+C`. После появления `/opt/saparguard/data/telethon.session` запустите постоянный collector:

```bash
sudo systemctl enable --now saparguard-collector.service
systemctl status saparguard-api.service saparguard-collector.service
```

Логи: `journalctl -u saparguard-api -f`, `journalctl -u saparguard-collector -f` и файл из `LOG_PATH`. Файловый лог автоматически ротируется.

## Проверка

```bash
python -m compileall app alembic
pytest
```

Для production всегда ограничьте доступ к порту API firewall-ом или reverse proxy с аутентификацией: встроенной аутентификации в этом диагностическом UI пока нет.
