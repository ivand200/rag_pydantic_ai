import { expect, test, type Page } from "@playwright/test";

import { schemaPaths } from "./schema-paths";
import { expectValueMatchesSchema, readSchema } from "./schema-utils";

const resumedSessionId = "55555555-5555-5555-5555-555555555555";
const newSessionId = "66666666-6666-6666-6666-666666666666";

const lastMessage = {
  id: "77777777-7777-7777-7777-777777777777",
  role: "assistant",
  content: "Use the ingestion queue status before trusting retrieval.",
  status: "completed",
  created_at: "2026-05-03T11:05:00Z",
  model: null,
  retrieval_query: null,
  usage: null,
  sources: []
};

const initialSessions = [
  {
    id: resumedSessionId,
    title: "Ingestion readiness review",
    title_status: "generated",
    created_at: "2026-05-03T11:00:00Z",
    updated_at: "2026-05-03T11:05:00Z",
    last_message_at: "2026-05-03T11:05:00Z",
    last_message: lastMessage
  }
];

const resumedSession = {
  ...initialSessions[0],
  messages: [
    {
      id: "88888888-8888-8888-8888-888888888888",
      role: "user",
      content: "What should I check before using retrieval?",
      status: "completed",
      created_at: "2026-05-03T11:04:00Z",
      model: null,
      retrieval_query: null,
      usage: null,
      sources: []
    },
    lastMessage
  ]
};

const newSession = {
  id: newSessionId,
  title: "New chat",
  title_status: "pending",
  created_at: "2026-05-03T11:10:00Z",
  updated_at: "2026-05-03T11:10:00Z",
  last_message_at: null,
  messages: []
};

const createRequest = {
  method: "POST",
  path: "/api/chat/sessions"
};

const loadRequest = {
  method: "GET",
  path: `/api/chat/sessions/${resumedSessionId}`,
  session_id: resumedSessionId
};

test("chat session UI creates new chats and resumes the latest saved history", async ({ page }) => {
  expectValueMatchesSchema(initialSessions, readSchema(schemaPaths.chatSessionsList));
  expectValueMatchesSchema(createRequest, readSchema(schemaPaths.chatSessionCreateRequest));
  expectValueMatchesSchema(newSession, readSchema(schemaPaths.chatSessionCreate));
  expectValueMatchesSchema(loadRequest, readSchema(schemaPaths.chatSessionLoadRequest));
  expectValueMatchesSchema(resumedSession, readSchema(schemaPaths.chatSessionLoad));

  await page.route(`**/api/chat/sessions/${resumedSessionId}`, async (route) => {
    expect(route.request().method()).toBe("GET");
    await route.fulfill({ json: resumedSession });
  });

  await page.route("**/api/chat/sessions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: initialSessions });
      return;
    }

    if (route.request().method() === "POST") {
      await route.fulfill({ status: 201, json: newSession });
      return;
    }

    await route.fallback();
  });

  await routeDocuments(page);

  await page.goto("/?workspace-preview=1");

  await expect(page.getByRole("heading", { name: resumedSession.title })).toBeVisible();
  await expect(page.getByText("What should I check before using retrieval?")).toBeVisible();
  await expect(page.locator("article", { hasText: lastMessage.content })).toBeVisible();
  await expect(page.getByText("Most recent chat session resumed.")).toBeVisible();
  await expect(
    page.getByPlaceholder("Ask about your documents, code, or architecture specs...")
  ).toBeEnabled();

  await page.locator("aside").getByRole("button", { name: "New Chat" }).click();

  await expect(page.getByRole("heading", { name: "New chat", exact: true })).toBeVisible();
  await expect(page.getByText("New chat is saved")).toBeVisible();
  await expect(page.getByText(`session_id: ${newSessionId}`)).toBeVisible();
  await expect(
    page.getByText("New chat session created. Ask a question against the shared document pool.")
  ).toBeVisible();
});

test("chat session UI deletes the active saved session and clears chat state", async ({ page }) => {
  let deleteRequestCount = 0;

  await page.route(`**/api/chat/sessions/${resumedSessionId}`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: resumedSession });
      return;
    }

    if (route.request().method() === "DELETE") {
      deleteRequestCount += 1;
      await route.fulfill({ status: 204, body: "" });
      return;
    }

    await route.fallback();
  });

  await page.route("**/api/chat/sessions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: initialSessions });
      return;
    }

    await route.fallback();
  });

  await routeDocuments(page);

  await page.goto("/?workspace-preview=1");

  await expect(page.getByRole("heading", { name: resumedSession.title })).toBeVisible();
  await expect(page.getByText("What should I check before using retrieval?")).toBeVisible();

  await page.getByRole("button", { name: `Delete ${resumedSession.title}` }).click();

  expect(deleteRequestCount).toBe(1);
  await expect(page.locator("aside").getByText(resumedSession.title)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Chat History" })).toBeVisible();
  await expect(page.getByText("No session selected")).toBeVisible();
  await expect(
    page.getByText("Deleted active chat session. Create or select a saved chat to continue.")
  ).toBeVisible();
  await expect(
    page.getByPlaceholder("Ask about your documents, code, or architecture specs...")
  ).toBeDisabled();
});

test("authenticated workspace hides unsupported future controls", async ({ page }) => {
  await page.route("**/api/chat/sessions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }

    await route.fallback();
  });

  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }

    await route.fallback();
  });

  await page.goto("/?workspace-preview=1");

  await expect(page.getByRole("button", { name: "Workspace", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Knowledge Base", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Support", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Analytics", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sources", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Models", exact: true })).toHaveCount(0);
  await expect(page.getByPlaceholder("Search across system...")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Export", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Deploy", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "All Documents", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Document Pools" }).click();

  await expect(page.getByRole("button", { name: "All Files", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "PDFs", exact: true })).toHaveCount(0);
});

async function routeDocuments(page: Page) {
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }

    await route.fallback();
  });
}
