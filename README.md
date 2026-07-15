# SaparGuard

SaparGuard collects public Telegram transport announcements, processes their text and media, and provides an internal review system for observed profiles, vehicles, relationships and conflicts. It also provides a separate citizen-facing account and complaint workflow. Application users are never mixed with Telegram authors or observed transport profiles.

## Architecture and pipeline

- FastAPI serves JSON API, Jinja2 pages and HTMX fragments; frontend assets are built locally and shipped with the image.
- Telethon collector saves messages and media jobs to PostgreSQL.
- Text-analysis worker extracts message type, contacts, routes, locations and vehicle information.
- Profile-resolution worker creates observed profiles, vehicle links, relationship evidence and conflicts.
- PostgreSQL stores all durable application, review and complaint data. Alembic owns schema changes.

Collected observations are not verified identities and do not establish a violation or vehicle ownership.

## Access and accounts

All working pages and internal `/api/*` endpoints require a signed JWT stored in an HttpOnly, SameSite cookie. Tokens are never stored in `localStorage`.

- `citizen` / «Гражданин»: manages an account, submits complaints and sees only their own complaints.
- `worker` / «Сотрудник»: uses the existing analytical system and processes complaints.
- `admin` / «Администратор»: has all worker access plus `/admin/users` account management.

Citizens cannot access collected Telegram data, profiles, vehicles, graph, review, conflicts, sources, quality or internal API. Workers cannot open administration. Server-side checks return an HTML 403 page for browser requests and JSON 403 for API requests.

Local registration is email-only and always creates an active citizen account. Passwords must contain at least 12 characters and are stored only as bcrypt hashes. Google OAuth/OIDC uses a verified Google email; matching local accounts are linked instead of duplicated. If Google is unconfigured, the login screen remains usable and shows the disabled `😢 Не работает...` fallback.

An administrator can search, filter, create, edit, block, soft-delete and assign roles to accounts. Soft deletion preserves complaint and action history. The last active administrator cannot be deleted, blocked or demoted.

## Environment

Copy `.env.example` to `.env`. At minimum configure `DATABASE_URL` and a strong `JWT_SECRET`.

```text
JWT_SECRET=
JWT_EXPIRE_MINUTES=480
DEFAULT_ADMIN_EMAIL=
DEFAULT_ADMIN_PASSWORD=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
```

On first API start, `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` create one active administrator. The password must be at least 12 characters. Bootstrap is idempotent: an existing account is neither recreated nor has its password rotated. Do not place real passwords, Google secrets, Telegram sessions or review exports in Git.

## Pages and API

- Public: `/auth/login`, `/auth/register`, Google callback, static files and `/health`.
- Citizen: `/complaints`, `/complaints/new`, `/complaints/{id}`, `/auth/me`.
- Staff: `/`, `/sources`, `/messages`, `/review`, `/profiles`, `/vehicles`, `/graph`, `/conflicts`, `/quality` and internal `/api/*`.
- Administrator: `/admin/users`.

The graph has a bounded API response and discloses truncation. Profiles, vehicles, profile/vehicle timelines and conflicts use visible pagination. Evidence links use the internal message ID and do not rely on full-text search.

## Local development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
corepack enable
cd web-assets && pnpm install --frozen-lockfile && pnpm build && cd ..
cp .env.example .env
# configure DATABASE_URL, JWT_SECRET and optional Telegram/Google settings
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
# separate terminals, as required
.venv/bin/python -m app.collector.service
.venv/bin/python -m app.processing.text.worker
.venv/bin/python -m app.processing.profiles.worker
```

For CSS/asset watch mode use `cd web-assets && pnpm dev`. No frontend dependency is loaded from a CDN.

## Docker and systemd

```bash
cp .env.example .env
docker compose up --build
```

The Compose migration service runs `alembic upgrade head` before API and workers. It does not reset PostgreSQL data. For a non-Docker deployment, build the bundle with `./scripts/prepare_deploy.sh` and install it with `scripts/install.sh`; systemd unit files live in `deployment/systemd/`.

## Review and evaluation

Synthetic fixtures in `evaluation/datasets` are smoke tests only; they do not demonstrate production quality. Human-reviewed data must remain in access-controlled local storage and must not be committed.

Prepare a 100–200 message reviewed dataset with at least 20–30 samples per important message type, separate positive/negative examples, images with and without plates, and profile pairs for both same-subject and different-subject cases. Export false-positive and false-negative reports after review.

```bash
.venv/bin/python -m app.evaluation.export_reviewed \
  --output-dir evaluation/local-reviewed --min-reviewed 1 --include-sensitive-values
.venv/bin/python -m app.evaluation.cli run \
  --dataset-dir evaluation/local-reviewed/human-reviewed-... \
  --output-dir evaluation/local-reviewed/reports
```

## Verification

```bash
.venv/bin/python -m compileall app alembic
.venv/bin/ruff check app tests
.venv/bin/pytest -q
.venv/bin/alembic heads
docker compose config
```

Integration tests require an isolated `POSTGRES_TEST_URL` whose database name ends in `_test` or `_integration`; see [the integration-test guide](docs/postgresql-integration-tests.md). Browser smoke testing must use a clean PostgreSQL instance and verify login, fallback Google UI, complaint handling, role boundaries, filters, pagination, evidence links and all staff pages.

## Limits

The system processes only configured Telegram sources. Extraction and scoring are deterministic, evidence-backed aids for review, not a decision system. Google login requires valid Google OAuth configuration. Feature work is frozen after this release; subsequent changes should be bug fixes, tests and reliability improvements only.
