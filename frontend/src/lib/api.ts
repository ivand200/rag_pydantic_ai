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

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type ClerkTokenProvider = () => Promise<string | null>;

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function fetchCurrentUser(getToken: ClerkTokenProvider): Promise<AppUser> {
  const token = await getToken();

  if (!token) {
    throw new ApiError(401, "No active Clerk session token is available.");
  }

  const response = await fetch(`${API_BASE_URL}/api/me`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json"
    }
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<AppUser>;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string; message?: string };
    return body.detail ?? body.message ?? `Request failed with status ${response.status}.`;
  } catch {
    return `Request failed with status ${response.status}.`;
  }
}
