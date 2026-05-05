# Tech Steering

## Stack

- Backend: Python 3.12+, FastAPI, Pydantic Settings, PyJWT with crypto support, SQLAlchemy 2.0, psycopg 3, Alembic, pgvector, Pydantic AI, OpenAI SDK, pypdf, boto3/S3-compatible storage, Uvicorn, uv, pytest, and ruff.
- Frontend: Vue 3, TypeScript, Vite, `@clerk/vue`, Tailwind CSS v4, daisyUI, and `lucide-vue-next`.
- Browser/e2e: Playwright, including Clerk schema-capture tests where real Clerk credentials are available.
- Local runtime: Docker Compose with backend, ingestion worker, frontend, pgvector-enabled Postgres, and MinIO services.
- Root orchestration: `Makefile` wraps common setup, infrastructure, migration, lint, test, build, and Compose validation commands.
- RAG runtime uses Pydantic AI/OpenAI for query rewrite and answer generation, OpenAI embeddings behind an embedding-provider boundary, exact pgvector search, a Postgres ingestion queue with `SKIP LOCKED`, and deterministic evals with local model/embedding doubles.

## Key Services / Infrastructure

- Clerk remains external SaaS in the current implementation; there is no local auth database.
- Postgres stores app-owned data: local `app_users`, document metadata/chunks/embeddings, ingestion jobs, chat sessions/messages, and source attribution records.
- MinIO provides local S3-compatible original-document storage through an object-storage boundary.
- Backend runs on port `8000` and exposes `GET /health`, protected document APIs, protected chat/session APIs including owner-scoped session deletion, and SSE-style streaming chat responses.
- Frontend runs on port `5173` and calls the backend through `VITE_API_BASE_URL`.
- Docker Compose wires Postgres, MinIO bucket setup, backend, worker, and frontend startup through health checks or service dependencies.

## Engineering Conventions

- Backend startup goes through `app.main:create_app`, with route modules under `backend/app/api`.
- Backend settings live in `backend/app/core/config.py` and are sourced from environment variables and local `.env` files.
- Authentication is exposed to route code through FastAPI dependencies, especially `get_current_user`; route callers should not depend on JWT parsing internals.
- Local app user persistence is exposed through a narrow user-sync boundary; callers should depend on local app user identity, not raw Clerk ids or SQLAlchemy details.
- Protected frontend-to-backend calls use `Authorization: Bearer <Clerk session token>`.
- Frontend backend calls belong in `frontend/src/lib/api.ts`; UI surfaces should call that interface instead of hand-rolling fetch behavior.
- Frontend stateful RAG workspace behavior belongs in Vue composables under `frontend/src/composables`; visual components should consume those interfaces instead of owning API orchestration directly.
- Document upload/list/delete behavior belongs behind the backend document service and object-storage interface; route code should not expose object keys or storage SDK details.
- Ingestion behavior belongs in the worker/service boundary; callers should rely on document/job status transitions rather than extraction, retry, or chunking internals.
- RAG orchestration depends on explicit embedding, query-rewrite, and answer-generation interfaces so tests and evals can use deterministic doubles without OpenAI calls.
- Durable frontend visual-system choices belong in [Design Steering](./design.md); task docs may explore variants, but accepted direction should be summarized there.
- Contract tests should stay near public behavior: backend health, CORS, protected auth/user persistence behavior, document and chat APIs, stream event contracts, migrations/schema, deterministic retrieval/RAG evals, frontend type/build, and e2e schema checks when credentials allow.
- Do not commit secrets. `.env.example` documents names; local `.env` holds values.

## Related Steering Docs

- [Product Steering](./product.md)
- [Structure Steering](./structure.md)
- [Design Steering](./design.md)

## Technical Constraints

- `VITE_CLERK_PUBLISHABLE_KEY` is required for the Clerk-enabled frontend.
- `CLERK_JWT_PUBLIC_KEY` is required for protected backend routes; without it, protected calls return unauthorized.
- `BACKEND_CORS_ORIGINS` is a comma-separated allow-list. The backend CORS policy supports the implemented browser contracts: `GET`, `POST`, `DELETE`, and `OPTIONS` with `Authorization` and `Content-Type` headers.
- `DATABASE_URL` is required for protected backend routes that sync local app users and for Alembic migrations.
- `TEST_DATABASE_URL` can override the database used by DB-backed backend tests; tests skip DB-backed checks when Postgres is unreachable.
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CHAT_MODEL`, and `EMBEDDING_MODEL` are required only for real model-backed ingestion/chat paths. Unit tests, mocked e2e checks, and deterministic evals use doubles and must not call OpenAI.
- Real Clerk e2e capture can require `CLERK_TESTING_TOKEN` or `CLERK_SECRET_KEY` plus test user credentials.
- Real document/chat schema capture can require bearer tokens for the backend, and real stream capture also requires model configuration and suitable source data.
