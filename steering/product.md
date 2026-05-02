# Product Steering

## Purpose

- Build an internal RAG service where authenticated users ask questions about a shared document pool and receive answers with source attribution.
- Keep the implementation clear and reviewable: it should demonstrate strong boundaries, security awareness, tests, and a polished internal-tool experience.
- Current repository state is iteration 1 plus local app-user persistence: an authenticated app shell, protected backend identity contract, Postgres-backed `app_users` projection, Docker Compose runtime, and initial tests. RAG, documents, and chat are future iterations.

## Users / Actors

- Internal authenticated users, expected to be a small group of about 10 people.
- Visitors or teammates who need to register, sign in, and sign out before using protected app surfaces.
- Developers and reviewers evaluating architecture, contracts, security posture, and maintainability.
- Clerk is the current external identity and session provider.

## Core Workflows

- Register, sign in, and sign out through Clerk-hosted frontend flows.
- Access an authenticated app shell and call a protected backend identity endpoint that creates or updates the local app user.
- Future: upload `.txt`, `.pdf`, and `.md` documents into a shared pool.
- Future: ask questions about uploaded documents and see answers with source document attribution.
- Future: keep user-scoped chat history, start new chat sessions, and name sessions from the first user message using the model.
- Future: allow any authenticated user to delete any document from the shared pool.

## Core Domain Concepts

- Authenticated user: a Clerk-backed identity used by the frontend and normalized by the backend.
- Local app user: app-owned identity row synced from Clerk and intended as the future foreign-key target for documents, chat sessions, audits, and permissions.
- Session: Clerk session for current access; future chat sessions are separate product concepts.
- Shared document pool: all uploaded documents are shared across users rather than private per user.
- Document: future upload target limited to `.txt`, `.pdf`, and `.md` inputs.
- RAG answer: future model output grounded in uploaded documents and accompanied by source attribution.

## Scope Boundaries

- The current implementation must not imply that document upload, RAG answers, chat history, pgvector retrieval, queues, or evals already exist.
- This is an internal tool, not a public multi-tenant SaaS product.
- Clerk owns registration, login, logout, sessions, and identity data in the current architecture; the app does not own auth tables.
- The app owns local app-user references for app data; it must not become the source of truth for authentication.
- Any-user document deletion is an explicit product direction, not a permissions accident, and will need careful security review when implemented.

## Durable Constraints

- Use OpenAI-backed configuration for the planned RAG version unless explicit product direction changes.
- Keep future OpenAI/RAG settings documented but optional until RAG behavior is implemented.
- Future app-owned records should reference the local app user rather than raw Clerk identifiers.
- Treat authentication, document upload, document deletion, retrieval, citations, and LLM behavior as security-sensitive surfaces.
- Avoid a generic throwaway UI; even scaffold screens should feel like a focused internal workspace.
