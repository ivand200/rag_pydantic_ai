# Structure Steering

## Repository Shape

- Root files hold project setup docs, Docker Compose runtime wiring, environment examples, and task/source briefs.
- `backend/` owns the FastAPI service, app-owned database access, Alembic migrations, backend package metadata, Dockerfile, and pytest suite.
- `frontend/` owns the Vite Vue app, frontend package metadata, Dockerfile, Playwright config, and e2e schema baselines.
- `tasks/` holds task-specific spec workflow artifacts when present; durable project guidance belongs in `steering/`.

## Entry Points

- Start with `README.md` for local setup, checks, and Docker Compose usage.
- Local full-stack runtime starts at root with `docker compose up --build`.
- Backend execution starts in `backend/app/main.py` through `create_app()` and module-level `app`.
- Backend route behavior starts in `backend/app/api/health.py` and `backend/app/api/me.py`.
- Database migrations start from `backend/alembic.ini` and `backend/alembic/`.
- Frontend execution starts in `frontend/src/main.ts`; the current app shell lives in `frontend/src/App.vue`.
- Frontend backend calls start in `frontend/src/lib/api.ts`.
- Frontend e2e behavior starts from `frontend/playwright.config.ts` and tests under `frontend/e2e/`.

## Architectural Conventions

- Keep backend route modules thin. Cross-cutting concerns such as auth and settings should stay behind dependencies and config helpers.
- Keep Clerk token verification hidden behind the backend auth dependency; routes should consume normalized identity or local app user identity, not raw JWT claims.
- Keep SQLAlchemy session setup, model mapping, and upsert mechanics behind the DB/user persistence boundary.
- Keep frontend HTTP behavior centralized in `src/lib` so auth headers, base URLs, and error handling have one contract.
- Split frontend components or backend services only when a real workflow or domain boundary makes the current files too broad.
- Add pgvector, queues, and RAG services only with the iteration that implements document or chat behavior.

## Module Contract

- `GET /health` is public and returns service health as `{"status": "ok"}`.
- `GET /api/me` is protected and requires `Authorization: Bearer <Clerk session token>`.
- Missing, invalid, or unverifiable bearer tokens return `401`.
- On successful authentication, `GET /api/me` syncs a local `app_users` row and returns local app user identity: `id`, `email`, `first_name`, and `last_name`.
- Callers and tests must not depend on JWT library choice, claim lookup order, public key normalization, SQLAlchemy helper order, upsert SQL, router registration order, visual component structure, or Docker image layer details.
- App-owned tables should reference `app_users.id`, not raw Clerk identifiers.
- Do not add frontend UI or API clients that assume document, RAG, chat, queue, or eval endpoints exist before those boundaries are implemented.

## Module Interface Map

| Boundary | Owns | Public Interface | Hidden Details | Tests / Review Signals |
| --- | --- | --- | --- | --- |
| Backend API app | FastAPI app creation, route registration, CORS policy | `GET /health`, `GET /api/me` | App factory mechanics, router wiring, middleware order | `backend/tests/test_health.py`, `backend/tests/test_cors.py`, `backend/tests/test_me.py`; deeper review for public routes, CORS, auth, or mutating methods |
| Auth identity | Clerk JWT verification and normalized current user | `get_current_user` dependency returns `CurrentUser` or raises `401` | PyJWT calls, key formatting, claim extraction fallback order | `backend/tests/test_me.py`; deeper review for provider changes, token validation, permissions, or claim contract changes |
| App user persistence | Local user projection and future app-owned FK target | `app_users.id`, `get_current_app_user`, `GET /api/me` local user response | SQLAlchemy model details, upsert SQL, timestamps, DB session lifecycle | `backend/tests/test_me.py`, `backend/tests/test_database_schema.py`; deeper review for migrations, PII fields, constraints, or data integrity |
| Frontend auth shell / API client | Clerk session UI and protected local identity call | Sign-in/sign-up/sign-out surfaces, `fetchCurrentUser(getToken)` returning local app user | Clerk component layout, token retrieval timing, status copy | `npm run type-check`, `npm run build`, `npm run e2e:clerk` when configured; deeper review for auth UX, token flow, or backend contract changes |
| Runtime and configuration | Local service wiring and env-name contract | `.env.example`, `docker compose up --build`, backend `8000`, frontend `5173`, Postgres `5432`, `DATABASE_URL` | Container image layers, healthcheck implementation, dev-server flags, volume internals | `docker compose config`, CI workflow; deeper review for persistence, secrets, ports, migrations, or new infrastructure services |

## Where To Put New Work

- New backend routes go under `backend/app/api`; add shared dependencies in `backend/app/dependencies.py` only when route modules need them.
- Backend configuration changes go in `backend/app/core/config.py`, `.env.example`, and README setup docs together.
- Auth-provider behavior belongs in `backend/app/auth` and the Clerk frontend bootstrap, not scattered through route handlers or components.
- App-owned persistence work belongs under `backend/app/db`, `backend/app/models`, `backend/app/users`, and Alembic migrations.
- New frontend API calls go in `frontend/src/lib`; app UI can stay in `App.vue` until repeated surfaces justify component extraction.
- New backend tests go under `backend/tests`; e2e or schema-contract checks go under `frontend/e2e`.
- Future RAG/document/chat work should introduce explicit backend domain modules, persistence/migration ownership, and contract tests at the API boundary rather than leaking storage or prompt internals into callers.
