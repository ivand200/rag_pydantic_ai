# Tech Steering

## Stack

- Backend: Python 3.12+, FastAPI, Pydantic Settings, PyJWT with crypto support, SQLAlchemy 2.0, psycopg 3, Alembic, Uvicorn, uv, pytest, and ruff.
- Frontend: Vue 3, TypeScript, Vite, `@clerk/vue`, Tailwind CSS v4, daisyUI, and `lucide-vue-next`.
- Browser/e2e: Playwright, including Clerk schema-capture tests where real Clerk credentials are available.
- Local runtime: Docker Compose with backend, frontend, and Postgres services.
- Future RAG direction from product/task evidence: Pydantic AI, OpenAI, pgvector, a Postgres queue with `SKIP LOCKED`, and a RAG eval suite.

## Key Services / Infrastructure

- Clerk remains external SaaS in the current implementation; there is no local auth database.
- Postgres stores app-owned data, starting with the local `app_users` projection of Clerk identities.
- Backend runs on port `8000` and exposes `GET /health`.
- Frontend runs on port `5173` and calls the backend through `VITE_API_BASE_URL`.
- Docker Compose wires Postgres, backend, and frontend startup through health checks.

## Engineering Conventions

- Backend startup goes through `app.main:create_app`, with route modules under `backend/app/api`.
- Backend settings live in `backend/app/core/config.py` and are sourced from environment variables and local `.env` files.
- Authentication is exposed to route code through FastAPI dependencies, especially `get_current_user`; route callers should not depend on JWT parsing internals.
- Local app user persistence is exposed through a narrow user-sync boundary; callers should depend on local app user identity, not raw Clerk ids or SQLAlchemy details.
- Protected frontend-to-backend calls use `Authorization: Bearer <Clerk session token>`.
- Frontend backend calls belong in `frontend/src/lib/api.ts`; UI surfaces should call that interface instead of hand-rolling fetch behavior.
- Contract tests should stay near public behavior: backend health, CORS, protected auth/user persistence behavior, migrations/schema, frontend type/build, and e2e schema checks when credentials allow.
- Do not commit secrets. `.env.example` documents names; local `.env` holds values.

## Related Steering Docs

- [Product Steering](./product.md)
- [Structure Steering](./structure.md)

## Technical Constraints

- `VITE_CLERK_PUBLISHABLE_KEY` is required for the Clerk-enabled frontend.
- `CLERK_JWT_PUBLIC_KEY` is required for protected backend routes; without it, protected calls return unauthorized.
- `BACKEND_CORS_ORIGINS` is a comma-separated allow-list. The current backend CORS policy only needs `GET` and `OPTIONS`; mutating routes and uploads must revisit this.
- `DATABASE_URL` is required for protected backend routes that sync local app users and for Alembic migrations.
- `TEST_DATABASE_URL` can override the database used by DB-backed backend tests; tests skip DB-backed checks when Postgres is unreachable.
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `CHAT_MODEL` are documented for future RAG work and should not become required for the auth shell.
- Real Clerk e2e capture can require `CLERK_TESTING_TOKEN` or `CLERK_SECRET_KEY` plus test user credentials.
