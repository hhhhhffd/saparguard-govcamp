# SaparGuard Telegram Collector

Сервис сохраняет сырые сообщения выбранных Telegram-групп и каналов в PostgreSQL. На этом этапе он не выполняет AI-анализ, не скачивает медиа и не принимает автоматических решений.

Компоненты разделены: `api` отвечает за FastAPI и Web UI, а `collector` — независимый Telethon-процесс. Поэтому просмотр уже записанных данных продолжает работать при остановленном collector.

## Возможности

- пользовательская Telethon-сессия в отдельном локальном файле;
- источники по публичному username или числовому ID, управляемые через UI/API;
- первичная история с лимитом, датой начала и сохранением прогресса;
- новые, отредактированные и удалённые сообщения;
- UPSERT по `(telegram_chat_id, telegram_message_id)`;
- сохранение Telegram-фото и изображений-документов в сжатом JPEG;
- постоянная PostgreSQL-очередь обработки медиа и распознавание номерных знаков FastALPR;
- мягкое удаление источника: сообщения остаются в БД;
- API, UI, Docker Compose, Alembic и systemd-установка.

## Быстрый старт в Docker

```bash
cp .env.example .env
# заполните TELEGRAM_API_ID и TELEGRAM_API_HASH
docker compose up --build
```

Откройте `http://localhost:8000`. Добавьте источник через страницу «Источники». При первом запуске collector Telethon запросит авторизацию в интерактивном терминале; после неё session-файл будет храниться в Docker volume `telethon_data`.

История ограничена `COLLECTOR_HISTORY_DAYS=7`: старые сообщения, изображения и задачи распознавания не сохраняются. Уже сохранённые записи автоматически не удаляются. Интерфейс использует `DISPLAY_TIMEZONE` и показывает даты как `HH.mm.ss DD.MM.YYYY`; API продолжает возвращать ISO 8601 UTC timestamps.

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
- `GET /api/messages` — cursor/keyset-пагинация, поиск и фильтры для интеграций;
- `GET /api/messages/{id}` — полная карточка с медиа, статусом обработки и номерами;
- `GET /api/media/{id}` — сжатое сохранённое изображение без раскрытия пути на сервере;
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

Если Telegram не доставляет код на телефон, установите `TELEGRAM_AUTH_MODE=qr` и запустите collector в интерактивном терминале. Он отобразит QR; сканируйте его в Telegram через «Настройки → Устройства → Подключить устройство». При включённой 2FA терминал дополнительно запросит пароль. QR-токен не пишется в логи и действует недолго.

Логи: `journalctl -u saparguard-api -f`, `journalctl -u saparguard-collector -f` и файл из `LOG_PATH`. Файловый лог автоматически ротируется.

## Фото и номера

Collector создаёт постоянное задание PostgreSQL для каждого `message.photo` и документа с MIME-типом `image/*`. Один media worker внутри collector скачивает файл только перед обработкой, исправляет EXIF-ориентацию, удаляет метаданные, сжимает до JPEG (max 1600px) и сохраняет по SHA-256 в `data/media/`. Затем один лениво созданный FastALPR instance запускает CPU-распознавание. Ошибки повторяются согласно `MEDIA_JOB_MAX_ATTEMPTS`, после чего фиксируются как `failed`; они не останавливают collector.

На VPS с 1 ГБ RAM сохраняйте `ALPR_WORKER_COUNT=1`, `API_WORKER_COUNT=1` и лимиты потоков из `.env.example`. FastALPR при первой обработке может скачать модели, поэтому collector должен иметь исходящий доступ к интернету в этот момент.

## Проверка

```bash
python -m compileall app alembic
pytest
```

Для production всегда ограничьте доступ к порту API firewall-ом или reverse proxy с аутентификацией: встроенной аутентификации в этом диагностическом UI пока нет.
