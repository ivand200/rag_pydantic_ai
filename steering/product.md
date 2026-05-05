# Product Steering

## Purpose

- Build an internal RAG service where authenticated users ask questions about a shared document pool and receive answers with source attribution.
- Keep the implementation clear and reviewable: it should demonstrate strong boundaries, security awareness, tests, and a polished internal-tool experience.
- Current repository state includes the authenticated app shell, protected backend identity contract, Postgres-backed `app_users` projection, shared document upload/list/delete, ingestion worker, pgvector retrieval, streaming document-grounded chat, source citations, deterministic evals, and Docker Compose runtime.

## Users / Actors

- Internal authenticated users, expected to be a small group of about 10 people.
- Visitors or teammates who need to register, sign in, and sign out before using protected app surfaces.
- Developers and reviewers evaluating architecture, contracts, security posture, and maintainability.
- Clerk is the current external identity and session provider.

## Core Workflows

- Register, sign in, and sign out through Clerk-hosted frontend flows.
- Access an authenticated app shell and call a protected backend identity endpoint that creates or updates the local app user.
- Upload `.txt`, `.pdf`, and `.md` documents into a shared pool.
- Ask questions about uploaded documents and see answers with source document attribution.
- Keep user-scoped chat history, start new chat sessions, and name sessions from the first user message using the model or deterministic fallback.
- Delete owned chat sessions when they are no longer useful.
- Allow any authenticated user to delete any document from the shared pool through explicit tombstone behavior.

## Core Domain Concepts

- Authenticated user: a Clerk-backed identity used by the frontend and normalized by the backend.
- Local app user: app-owned identity row synced from Clerk and intended as the future foreign-key target for documents, chat sessions, audits, and permissions.
- Session: Clerk session for current access; chat sessions are user-owned conversation records separate from Clerk sessions.
- Shared document pool: all uploaded active documents are shared across users rather than private per user.
- Document: upload target limited to `.txt`, `.pdf`, and `.md` inputs, with original-file storage, ingestion state, and soft deletion.
- RAG answer: model output grounded in uploaded documents and accompanied by source attribution, or an explicit no-source answer when retrieval finds no evidence.

## Scope Boundaries

- Implemented surfaces must distinguish available document/chat/RAG behavior from future-only controls such as original-file viewing or broader admin workflows.
- This is an internal tool, not a public multi-tenant SaaS product.
- Clerk owns registration, login, logout, sessions, and identity data in the current architecture; the app does not own auth tables.
- The app owns local app-user references for app data; it must not become the source of truth for authentication.
- Chat sessions are user-owned records; missing or cross-user session ids should not leak ownership information.
- Any-user document deletion is an explicit product direction, not a permissions accident, and remains security-sensitive through tombstone/audit behavior.

## Durable Constraints

- Use OpenAI-backed configuration for RAG ingestion, retrieval, and chat behavior unless explicit product direction changes.
- Keep OpenAI/RAG settings documented and avoid making deterministic tests or evals depend on external model calls.
- Future app-owned records should reference the local app user rather than raw Clerk identifiers.
- Treat authentication, document upload, document deletion, retrieval, citations, and LLM behavior as security-sensitive surfaces.
- Avoid a generic throwaway UI; even scaffold screens should feel like a focused internal workspace.
- Treat [Design Steering](./design.md) as the durable source for RAG Architect UI direction and future-feature honesty in frontend surfaces.
