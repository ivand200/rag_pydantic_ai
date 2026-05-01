# RAG Service

Iteration 1 is a FastAPI backend, Vite Vue/DaisyUI frontend, Clerk authentication shell, and local Docker Compose runtime. Clerk is external, and there is no local Postgres service in this iteration.

## Configuration

Create a local `.env` from `.env.example` and fill the Clerk values:

```sh
cp .env.example .env
```

Required for Clerk auth:

- `VITE_CLERK_PUBLISHABLE_KEY`: Clerk publishable key for the Vue app.
- `CLERK_JWT_PUBLIC_KEY`: Clerk JWT public key used by FastAPI to verify bearer tokens.

Runtime wiring:

- `VITE_API_BASE_URL`: browser-facing backend URL. The Compose default is `http://localhost:8000`.
- `BACKEND_CORS_ORIGINS`: comma-separated browser origins allowed to call the backend. The default is `http://localhost:5173`.

Future RAG settings are documented but unused in iteration 1:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `CHAT_MODEL`

## Run With Docker Compose

Start the full local stack:

```sh
docker compose up --build
```

The frontend runs at `http://localhost:5173`.
The backend runs at `http://localhost:8000`, with health available at `http://localhost:8000/health`.

Clerk sign-in and sign-up happen through Clerk-hosted flows in the frontend. The frontend sends Clerk session tokens to the backend as `Authorization: Bearer <token>` when calling protected routes such as `GET /api/me`.

## Direct Development

Backend:

```sh
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```sh
cd frontend
npm install
npm run dev
```

## Checks

Backend tests:

```sh
cd backend
uv run pytest
```

Frontend type check and build:

```sh
cd frontend
npm run type-check
npm run build
```

Opt-in real Clerk e2e schema capture:

```sh
cd frontend
E2E_WRITE_SCHEMAS=1 npm run e2e:clerk
```

The public Clerk environment schema and unauthenticated backend auth schema run with the existing publishable key. Browser-origin Clerk client and signed-in `/api/me` schema capture require `CLERK_TESTING_TOKEN` or `CLERK_SECRET_KEY`; signed-in capture also requires `E2E_CLERK_USER_EMAIL` and `E2E_CLERK_USER_PASSWORD`.

Docker Compose validation:

```sh
docker compose config
```
