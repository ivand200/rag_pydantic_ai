export interface AppUser {
  id: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
}

export interface ApiStatus {
  state: "idle" | "loading" | "ready" | "error";
  message: string;
  user?: AppUser;
}

export type DocumentStatus = "queued" | "processing" | "completed" | "failed" | string;
export type ChatMessageRole = "user" | "assistant" | string;
export type ChatMessageStatus = "completed" | string;

export interface DocumentRecord {
  id: string;
  filename: string;
  media_type: string;
  byte_size: number;
  status: DocumentStatus;
  uploaded_by: AppUser;
  uploaded_at: string;
  deleted: boolean;
  deleted_at?: string | null;
  failure_reason?: string | null;
}

export interface MessageSourceRecord {
  id: string;
  document_id: string;
  document_name: string;
  chunk_id: string;
  rank: number;
  score: number;
  excerpt: string;
  page_number?: number | null;
  section_title?: string | null;
  document_deleted_at?: string | null;
}

export interface ChatMessageRecord {
  id: string;
  role: ChatMessageRole;
  content: string;
  status: ChatMessageStatus;
  created_at: string;
  model?: string | null;
  retrieval_query?: string | null;
  usage?: Record<string, unknown> | null;
  sources: MessageSourceRecord[];
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  title_status: string;
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
  last_message?: ChatMessageRecord | null;
}

export interface ChatSessionDetail {
  id: string;
  title: string;
  title_status: string;
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
  messages: ChatMessageRecord[];
}

export interface ChatStreamDeltaEvent {
  text: string;
}

export interface ChatStreamFinalEvent {
  assistant_message_id: string;
  session_id: string;
  sources: MessageSourceRecord[];
  model?: string | null;
  usage?: Record<string, unknown> | null;
}

export interface ChatStreamErrorEvent {
  message: string;
  retryable: boolean;
}

export interface ChatStreamHandlers {
  onDelta: (event: ChatStreamDeltaEvent) => void;
  onFinal: (event: ChatStreamFinalEvent) => void;
  onError: (event: ChatStreamErrorEvent) => void;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type ClerkTokenProvider = () => Promise<string | null>;

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

export async function fetchCurrentUser(getToken: ClerkTokenProvider): Promise<AppUser> {
  const response = await fetch(`${API_BASE_URL}/api/me`, {
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<AppUser>;
}

export async function fetchDocuments(getToken: ClerkTokenProvider): Promise<DocumentRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/documents`, {
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<DocumentRecord[]>;
}

export async function uploadDocument(
  getToken: ClerkTokenProvider,
  file: File
): Promise<DocumentRecord> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/documents`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: form
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<DocumentRecord>;
}

export async function deleteDocument(
  getToken: ClerkTokenProvider,
  documentId: string
): Promise<DocumentRecord> {
  const response = await fetch(`${API_BASE_URL}/api/documents/${documentId}`, {
    method: "DELETE",
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<DocumentRecord>;
}

export async function fetchChatSessions(
  getToken: ClerkTokenProvider
): Promise<ChatSessionSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions`, {
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<ChatSessionSummary[]>;
}

export async function createChatSession(getToken: ClerkTokenProvider): Promise<ChatSessionDetail> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions`, {
    method: "POST",
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<ChatSessionDetail>;
}

export async function fetchChatSession(
  getToken: ClerkTokenProvider,
  sessionId: string
): Promise<ChatSessionDetail> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<ChatSessionDetail>;
}

export async function deleteChatSession(
  getToken: ClerkTokenProvider,
  sessionId: string
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: await authJsonHeaders(getToken)
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
}

export async function streamChatMessage(
  getToken: ClerkTokenProvider,
  sessionId: string,
  content: string,
  handlers: ChatStreamHandlers,
  options: { signal?: AbortSignal } = {}
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: {
      ...(await authJsonHeaders(getToken)),
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify({ content }),
    signal: options.signal
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  if (!response.body) {
    throw new ApiError(response.status, "Streaming response did not include a readable body.");
  }

  await parseSseStream(response.body, (event) => {
    if (event.event === "delta") {
      handlers.onDelta(readJsonEvent<ChatStreamDeltaEvent>(event.data, "delta"));
      return;
    }

    if (event.event === "final") {
      handlers.onFinal(readJsonEvent<ChatStreamFinalEvent>(event.data, "final"));
      return;
    }

    if (event.event === "error") {
      handlers.onError(readJsonEvent<ChatStreamErrorEvent>(event.data, "error"));
    }
  });
}

async function authJsonHeaders(getToken: ClerkTokenProvider): Promise<HeadersInit> {
  return {
    ...(await authHeaders(getToken)),
    Accept: "application/json"
  };
}

async function authHeaders(getToken: ClerkTokenProvider): Promise<HeadersInit> {
  const token = await getToken();

  if (!token) {
    throw new ApiError(401, "No active Clerk session token is available.");
  }

  return {
    Authorization: `Bearer ${token}`
  };
}

async function parseSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: { event: string; data: string }) => void
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = drainSseEvents(buffer, onEvent);

      if (done) {
        break;
      }
    }

    const remaining = buffer.trim();
    if (remaining) {
      emitSseEvent(remaining, onEvent);
    }
  } finally {
    reader.releaseLock();
  }
}

function drainSseEvents(buffer: string, onEvent: (event: { event: string; data: string }) => void) {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const chunks = normalized.split("\n\n");
  const remainder = chunks.pop() ?? "";

  for (const chunk of chunks) {
    emitSseEvent(chunk, onEvent);
  }

  return remainder;
}

function emitSseEvent(rawEvent: string, onEvent: (event: { event: string; data: string }) => void) {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of rawEvent.split("\n")) {
    if (line.startsWith(":") || line.length === 0) {
      continue;
    }

    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trimStart();
      continue;
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (dataLines.length > 0) {
    onEvent({ event, data: dataLines.join("\n") });
  }
}

function readJsonEvent<T>(data: string, eventName: string): T {
  try {
    return JSON.parse(data) as T;
  } catch (error) {
    throw new ApiError(200, `Invalid ${eventName} stream event payload.`);
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: string | { code?: string; message?: string };
      message?: string;
    };

    if (typeof body.detail === "string") {
      return body.detail;
    }

    return (
      body.detail?.message ??
      body.message ??
      body.detail?.code ??
      `Request failed with status ${response.status}.`
    );
  } catch {
    return `Request failed with status ${response.status}.`;
  }
}
