<div align="center">

<h1>SaparGuard</h1>
<hr>

**Decision support for transport control: public Telegram announcements in, explainable evidence-linked observations out**

![PYTHON](https://img.shields.io/badge/PYTHON-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FASTAPI](https://img.shields.io/badge/FASTAPI-0.116-009688?style=flat-square&logo=fastapi&logoColor=white)
![POSTGRESQL](https://img.shields.io/badge/POSTGRESQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![DOCKER](https://img.shields.io/badge/DOCKER-COMPOSE-2496ED?style=flat-square&logo=docker&logoColor=white)
![LICENSE](https://img.shields.io/badge/LICENSE-AGPL--3.0-blue?style=flat-square)

[Demo video](https://youtu.be/QLD-9kvcOsw) · [Presentation](https://drive.google.com/file/d/1YmO1dIrT4hKsplXm3NaKLobK7Hp_PQl_/view?usp=sharing) · [Quick start](#quick-start) · [Русская версия](docs/README.ru.md)

</div>

## What it is

SaparGuard is a prototype built for the GovTech Camp selection stage. Transport-control staff cannot manually review a large, fast-changing flow of public intercity transport announcements in Telegram. SaparGuard collects them, classifies messages, extracts phones, routes and vehicles, detects licence plates in images and ranks observations for review.

Every result is linked to its source message or image, with matched rules and confidence. A reviewer can correct the message type without changing the original observation.

> [!NOTE]
> The system does not establish a violation, ownership or identity. Its outputs are leads for human review.

## Highlights

- Collector for configured public Telegram sources (Telethon) with deduplication by source and message ID.
- Rule-based text analysis and FastALPR (ONNX) plate detection with OCR; no black-box decision model.
- Profile resolution that combines repeated identifiers and tracks conflicts.
- Staff workspace (review, profiles, vehicles, graph, quality) and a separate citizen complaint flow, with role-based access.

**Role:** sole developer of a one-person project, built for the GovTech Camp selection stage.

## Technical stack

| Category | Technologies |
| --- | --- |
| Core | Python 3.12, FastAPI, Uvicorn, Jinja2, HTMX, Alpine.js, Tailwind CSS |
| Data | PostgreSQL 16, SQLAlchemy 2 async ORM, asyncpg, Alembic |
| Analysis | Rule-based NLP, FastALPR (ONNX), evidence-based profile resolution and priority scoring |
| Integration | Telethon, Google OAuth/OIDC (Authlib) |
| Infrastructure | Docker Compose, systemd units, pnpm |

## Quick start

Requires Docker with Compose v2 and Telegram API credentials from [my.telegram.org/apps](https://my.telegram.org/apps).

```bash
cp .env.example .env
# set TELEGRAM_API_ID, TELEGRAM_API_HASH, JWT_SECRET, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
docker compose up --build
```

Compose applies the Alembic migrations, then starts the API, collector, text-analysis worker and profile-resolution worker. Open `http://localhost:8000`; the health check is `/health`.

> [!WARNING]
> Keep `.env`, Telegram session files and database backups out of Git. Generate a unique `JWT_SECRET` for every environment.

Checks: `ruff check app tests`, `pytest -q`, `alembic heads`. Integration tests need an isolated `POSTGRES_TEST_URL`, see [docs/postgresql-integration-tests.md](docs/postgresql-integration-tests.md).

## License

AGPL-3.0, see [LICENSE](LICENSE).
