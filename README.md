# SaparGuard

[Русская версия](docs/README.ru.md)

SaparGuard is a GovTech decision-support prototype for monitoring public intercity transport announcements in Telegram. It turns an unstructured stream of messages and images into explainable observations: message types, contacts, routes, vehicles, licence-plate detections and evidence-backed profiles.

The core problem is that transport-control staff cannot manually and consistently review a large, fast-changing flow of public announcements. SaparGuard automates collection and primary analysis, ranks observations for attention and preserves the original evidence; a responsible employee remains the final decision-maker.

> The system does not establish a violation, ownership or identity. Its outputs are leads for review, not automated enforcement decisions.

## Deliverables

- [Demo video / pitch](ADD_DEMO_VIDEO_URL)
- [Presentation](ADD_PRESENTATION_URL)
- [Live demo](ADD_LIVE_DEMO_URL)

## Problem, users and outcome

| Aspect | Description |
| --- | --- |
| Problem | Public transport announcements are heterogeneous, frequently duplicated and difficult to review manually. Important route, contact and vehicle signals remain scattered across text and images. |
| Primary user | Transport-control analyst or municipal employee who investigates patterns and prioritises a review queue. |
| Citizen user | A citizen who can submit and track an independent complaint without seeing internal Telegram observations. |
| Outcome | Faster triage of messages, evidence-linked profiles and a transparent basis for human review. |

## Technical stack

| Category | Technologies |
| --- | --- |
| Core | Python 3.12, FastAPI, Uvicorn, Jinja2, HTMX, Alpine.js, Tailwind CSS |
| Data | PostgreSQL 16, SQLAlchemy 2 async ORM, asyncpg, Alembic |
| AI / data-driven | Rule-based NLP classification, phone/route/vehicle extraction, FastALPR ONNX, OCR, evidence-based profile resolution and priority scoring |
| Integration | Telethon for public Telegram sources, Google OAuth/OIDC through Authlib |
| Infrastructure | Docker Compose, Docker, systemd deployment units, pnpm |

## Architecture

```mermaid
flowchart LR
    TG[Public Telegram sources] --> C[Telethon collector]
    C --> DB[(PostgreSQL)]
    C --> AQ[Text-analysis jobs]
    C --> MQ[Media-processing jobs]
    AQ --> TW[Text worker]
    MQ --> MW[Media worker]
    TW --> DB
    MW --> DB
    DB --> PW[Profile-resolution worker]
    PW --> DB
    DB --> API[FastAPI + Jinja2/HTMX]
    API --> S[Staff workspace]
    API --> U[Citizen complaints]
    S --> R[Human review and corrections]
    R --> DB
```

### Data flow

1. The collector receives messages only from configured public sources and stores the original text, metadata and media jobs.
2. The text worker classifies the message and extracts phones, routes, locations and vehicles. The media worker downloads images and runs licence-plate detection.
3. The profile worker combines repeated, explainable identifiers into observed profiles, vehicle links and possible conflicts.
4. The staff workspace shows each result together with its source message, matched rules, confidence and evidence. A reviewer can correct the message type without changing the original observation.

```mermaid
sequenceDiagram
    participant T as Telegram source
    participant C as Collector
    participant A as Analysis workers
    participant P as Profile resolver
    participant R as Reviewer
    participant D as PostgreSQL

    T->>C: Public message or image
    C->>D: Save source evidence and enqueue jobs
    A->>D: Save type, entities, routes and plate detections
    P->>D: Save profile links, score and conflicts
    R->>D: Confirm or correct the proposed message type
    Note over R,D: Human judgement is separate from automatic analysis
```

## AI / data-driven component

SaparGuard uses deterministic, inspectable processing rather than a black-box decision model.

```mermaid
flowchart TD
    M[Original message] --> CL[Message-type classifier]
    M --> EX[Entity extractors]
    I[Attached image] --> CV[FastALPR + OCR]
    CL --> E[Type, confidence, matched rules]
    EX --> E2[Phones, routes, locations, vehicles]
    CV --> E3[Licence plate candidates]
    E --> PR[Profile resolver and priority score]
    E2 --> PR
    E3 --> PR
    PR --> H[Human review queue]
```

### Explainability and human control

- The interface preserves the original message and displays classification confidence and matched rule evidence.
- Extracted phones, routes, vehicles and plate candidates are linked back to a concrete message or media file.
- Priority scores are based on visible factors such as recurring observations, route and vehicle evidence; they are not a legal or enforcement decision.
- Review annotations are stored separately from automatic analysis. A staff member can confirm, correct, skip or leave a draft annotation.
- Citizen accounts, internal staff accounts and observed Telegram authors are distinct data domains.

## Data

The prototype uses messages and images collected from configured public Telegram transport sources. Synthetic fixtures in `evaluation/datasets/` are included only for repeatable smoke checks; they are not a claim of production quality.

| Dataset layer | Main fields | Processing |
| --- | --- | --- |
| Source message | source, Telegram message ID, text, publication time, media marker | Deduplication by source/message ID and queueing for processing |
| Text analysis | message type, confidence, rule evidence, phones, routes, locations, vehicles | Normalisation and deterministic extraction |
| Media analysis | MIME type, image path, OCR plate candidates, confidence | Image processing and plate normalisation |
| Observed profile | evidence links, first/last seen, vehicle relations, priority factors | Profile resolution with conflict tracking |
| Human review | expected message type, comment, status, source-text hash | Keeps human judgement separate and detects stale annotations |

### Data limits

- Only configured public sources are processed; the dataset is not representative of all transport activity.
- Extraction quality depends on language variation, informal spelling, image quality and incomplete announcements.
- A detected contact, vehicle or plate is an observation, not verified ownership or a violation.
- Personal data, Telegram sessions, reviewed exports, database backups and secrets must not be committed.

## Architecture decisions

1. **FastAPI and async SQLAlchemy** — collection, API requests and workers perform network/database I/O concurrently; async support avoids blocking the application while Telegram or PostgreSQL is active.
2. **PostgreSQL as the durable system of record** — messages, jobs, evidence, review corrections and complaints require transactional consistency and migration-controlled schema changes. Alembic owns all schema evolution.
3. **Separate workers instead of synchronous request processing** — ingestion remains responsive while text analysis, image processing and profile resolution can retry independently and expose queue status to operators.

## Quick start with Docker Compose

### Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Telegram API credentials from [my.telegram.org/apps](https://my.telegram.org/apps) to run the collector

```bash
cp .env.example .env
```

Set at least the following in `.env`:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
JWT_SECRET=
DEFAULT_ADMIN_EMAIL=
DEFAULT_ADMIN_PASSWORD=
```

For Docker Compose, the application services use PostgreSQL at:

```text
postgresql+asyncpg://saparguard:saparguard@postgres:5432/saparguard
```

The Compose service is deliberately named `postgres`; use `postgres` as the host inside containers. The local `.env.example` URL uses `localhost` only for running the app outside Docker.

Start the stack:

```bash
docker compose up --build
```

Compose waits for PostgreSQL, applies Alembic migrations, then starts the API, collector, text-analysis worker and profile-resolution worker. Open `http://localhost:8000` after startup.

For the first Telethon session, use the configured `TELEGRAM_AUTH_MODE` (`phone` by default; `qr` is also supported) and keep the generated session file outside Git.

## Local development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
corepack enable
cd web-assets && pnpm install --frozen-lockfile && pnpm build && cd ..
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

Run these processes in separate terminals when required:

```bash
.venv/bin/python -m app.collector.service
.venv/bin/python -m app.processing.text.worker
.venv/bin/python -m app.processing.profiles.worker
```

Use `cd web-assets && pnpm dev` for frontend asset watch mode.

## Roles and key routes

| Role | Scope |
| --- | --- |
| Citizen | Account management, complaint submission and own complaint history |
| Worker | Dashboard, sources, messages, review, profiles, vehicles, graph, conflicts and quality controls |
| Administrator | Worker access plus user management |

Public health check: `/health`.

## Verification

```bash
.venv/bin/python -m compileall app alembic
.venv/bin/ruff check app tests
.venv/bin/pytest -q
.venv/bin/alembic heads
docker compose config
```

Integration tests require an isolated `POSTGRES_TEST_URL` whose database name ends in `_test` or `_integration`. See [docs/postgresql-integration-tests.md](docs/postgresql-integration-tests.md).

## Repository safety

Do not commit `.env`, Telegram sessions, database backups, media files, reviewed exports, generated evaluation reports or credentials. Use `.env.example` as the configuration template and generate a unique `JWT_SECRET` for every environment.
