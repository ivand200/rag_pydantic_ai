# Structure Steering

## Repository Shape

- Root files hold project setup docs, Docker Compose runtime wiring, environment examples, and task/source briefs.
- `backend/` owns the FastAPI service, app-owned database access, RAG/document/chat domains, ingestion worker, deterministic eval runner, Alembic migrations, backend package metadata, Dockerfile, and pytest suite.
- `frontend/` owns the Vite Vue app, frontend package metadata, Dockerfile, Playwright config, and e2e schema baselines.
- `steering/` owns durable product, tech, structure, and accepted design guidance.
- `tasks/` holds task-specific spec workflow artifacts when present; durable project guidance belongs in `steering/`.

## Entry Points

- Start with `README.md` for local setup, checks, and Docker Compose usage.
- Use the root `Makefile` for the main local command surface: setup, infrastructure, migrations, backend checks, frontend checks, and Compose validation.
- Local full-stack runtime starts at root with `docker compose up --build`.
- Backend execution starts in `backend/app/main.py` through `create_app()` and module-level `app`.
- Backend route behavior starts in `backend/app/api/health.py`, `backend/app/api/me.py`, `backend/app/api/documents.py`, and `backend/app/api/chat.py`.
- Document ingestion execution starts in `backend/app/ingestion/worker.py`.
- Deterministic RAG evals start with `cd backend && uv run python -m evals.runner`.
- Database migrations start from `backend/alembic.ini` and `backend/alembic/`.
- Frontend execution starts in `frontend/src/main.ts`; `frontend/src/App.vue` composes the authenticated workspace from shell, chat, document, and composable boundaries.
- Frontend backend calls, including document/session/message/stream clients, start in `frontend/src/lib/api.ts`.
- Frontend e2e behavior starts from `frontend/playwright.config.ts` and tests under `frontend/e2e/`.

## Architectural Conventions

- Keep backend route modules thin. Cross-cutting concerns such as auth and settings should stay behind dependencies and config helpers.
- Keep Clerk token verification hidden behind the backend auth dependency; routes should consume normalized identity or local app user identity, not raw JWT claims.
- Keep SQLAlchemy session setup, model mapping, and upsert mechanics behind the DB/user persistence boundary.
- Keep document workflow decisions behind `backend/app/documents`, object storage behind `backend/app/storage`, ingestion workflow behind `backend/app/ingestion`, retrieval behind `backend/app/retrieval`, and RAG/session/message orchestration behind `backend/app/chat`.
- Keep frontend HTTP behavior centralized in `src/lib` so auth headers, base URLs, and error handling have one contract.
- Keep stateful frontend document/chat workflows in `frontend/src/composables`; components should focus on rendering, user events, and accessible controls.
- Keep deterministic evals near backend RAG behavior in `backend/evals`; they may seed the test database and use local doubles, but must not require external model calls.

## Module Contract

- `GET /health` is public and returns service health as `{"status": "ok"}`.
- `GET /api/me` is protected and requires `Authorization: Bearer <Clerk session token>`.
- Missing, invalid, or unverifiable bearer tokens return `401`.
- On successful authentication, `GET /api/me` syncs a local `app_users` row and returns local app user identity: `id`, `email`, `first_name`, and `last_name`.
- `GET /api/documents`, `POST /api/documents`, and `DELETE /api/documents/{document_id}` are protected shared-document contracts. Upload accepts one `.txt`, `.md`, or `.pdf` file; list returns active shared documents; delete tombstones a document and is intentionally allowed for any authenticated user.
- `GET /api/chat/sessions`, `POST /api/chat/sessions`, `GET /api/chat/sessions/{session_id}`, `DELETE /api/chat/sessions/{session_id}`, and `POST /api/chat/sessions/{session_id}/messages/stream` are protected user-owned chat contracts. Missing or cross-user session ids return `404`.
- Streaming chat uses named SSE events: `delta`, `final`, and `error`. User messages are persisted before generation; assistant messages and sources are persisted only after successful completion.
- Chat-session deletion is owner-scoped hard deletion of the session and its message/source children; the frontend clears the active chat and aborts any active stream when deleting the active session.
- Retrieval returns completed, non-deleted chunks above the configured similarity threshold. No-source answers return no citations and must not invoke answer generation.
- Callers and tests must not depend on JWT library choice, claim lookup order, public key normalization, SQLAlchemy helper order, upsert SQL, router registration order, visual component structure, or Docker image layer details.
- App-owned tables should reference `app_users.id`, not raw Clerk identifiers.
- Do not expose object-storage keys, prompt internals, chunking internals, retry mechanics, or SQL/vector details as caller contracts.

## Module Interface Map

| Boundary | Owns | Public Interface | Hidden Details | Tests / Review Signals |
| --- | --- | --- | --- | --- |
| Backend API app | FastAPI app creation, route registration, CORS policy | `GET /health`, `GET /api/me` | App factory mechanics, router wiring, middleware order | `backend/tests/test_health.py`, `backend/tests/test_cors.py`, `backend/tests/test_me.py`; deeper review for public routes, CORS, auth, or mutating methods |
| Auth identity | Clerk JWT verification and normalized current user | `get_current_user` dependency returns `CurrentUser` or raises `401` | PyJWT calls, key formatting, claim extraction fallback order | `backend/tests/test_me.py`; deeper review for provider changes, token validation, permissions, or claim contract changes |
| App user persistence | Local user projection and app-owned FK target | `app_users.id`, `get_current_app_user`, `GET /api/me` local user response | SQLAlchemy model details, upsert SQL, timestamps, DB session lifecycle | `backend/tests/test_me.py`, `backend/tests/test_database_schema.py`; deeper review for migrations, PII fields, constraints, or data integrity |
| Document API / storage | Shared document upload/list/delete and original-file storage | `GET/POST/DELETE /api/documents`, document status and tombstone fields | object keys, storage SDK calls, filename normalization, ingestion job insert order | `backend/tests/test_documents.py`, `backend/tests/test_cors.py`; deeper review for upload validation, deletion permission, storage, or PII |
| Ingestion worker | Async extraction/chunk/embed pipeline | `python -m app.ingestion.worker`, document/job status transitions | claim SQL, retries, parser details, chunking details, embedding batch mechanics | `backend/tests/test_ingestion_worker.py`, `backend/tests/test_document_extraction.py`; deeper review for concurrency, retries, parser safety, or model calls |
| Retrieval / RAG orchestration | Query rewrite, embedding search, no-source policy, answer/citation assembly | `RAGOrchestrationService.generate`, retrieval results, citation payloads, deterministic eval command | prompt text, pgvector SQL, threshold calibration, source formatting | `backend/tests/test_retrieval.py`, `backend/tests/test_rag_orchestration.py`, `backend/evals/runner.py`; deeper review for grounding, deleted-doc exclusion, or external model use |
| Chat/session API | User-owned sessions/messages, owner-scoped deletion, and streaming answer contract | chat session endpoints and `delta`/`final`/`error` SSE events | persistence helper order, title fallback details, child-delete order, stream generator internals | `backend/tests/test_chat_sessions.py`, `backend/tests/test_chat_stream.py`; deeper review for ownership, deletion semantics, stream failure semantics, or source persistence |
| Frontend RAG shell / API client | Clerk UI, document pool, chat session UI, source readiness, streaming parser | Sign-in/sign-up/sign-out surfaces, typed `src/lib/api.ts` functions, `useDocuments`, `useChatSessions`, RAG Architect UI | Clerk component layout, token retrieval timing, component split, polling timer mechanics, local stream state | `npm run type-check`, `npm run build`, mocked e2e replay, real schema capture when configured; deeper review for auth UX, token flow, stream UI, polling, or backend contract changes |
| Runtime and configuration | Local service wiring and env-name contract | `.env.example`, `docker compose up --build`, backend `8000`, frontend `5173`, Postgres `5432`, MinIO `9000/9001`, worker service, `DATABASE_URL` | Container image layers, healthcheck implementation, dev-server flags, volume internals | `docker compose config`, CI workflow; deeper review for persistence, secrets, ports, migrations, workers, or new infrastructure services |

## Where To Put New Work

- New backend routes go under `backend/app/api`; add shared dependencies in `backend/app/dependencies.py` only when route modules need them.
- Backend configuration changes go in `backend/app/core/config.py`, `.env.example`, and README setup docs together.
- Auth-provider behavior belongs in `backend/app/auth` and the Clerk frontend bootstrap, not scattered through route handlers or components.
- App-owned persistence work belongs under `backend/app/db`, `backend/app/models`, `backend/app/users`, and Alembic migrations.
- New frontend API calls go in `frontend/src/lib`; document/chat workflow state belongs in `frontend/src/composables`; visual UI belongs under `frontend/src/components`.
- Durable UI-system changes should update `steering/design.md`; exploratory or task-specific UI variants should stay in `tasks/` until accepted.
- New backend tests go under `backend/tests`; e2e or schema-contract checks go under `frontend/e2e`.
- RAG/document/chat changes should stay in their explicit backend domain modules with contract tests at the API/service boundary rather than leaking storage, prompt, retry, or vector-search internals into callers.
