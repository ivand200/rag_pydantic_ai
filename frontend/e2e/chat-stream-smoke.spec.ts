import { expect, test, type Page } from "@playwright/test";

import { schemaPaths } from "./schema-paths";
import { expectValueMatchesSchema, readSchema } from "./schema-utils";

const sessionId = "99999999-9999-9999-9999-999999999999";
const sourceAssistantId = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const noSourceAssistantId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

const source = {
  id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  document_id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
  document_name: "Escalation Runbook.md",
  chunk_id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
  rank: 1,
  score: 0.93,
  excerpt: "Escalation must happen within two days.",
  page_number: 2,
  section_title: "Escalation",
  document_deleted_at: null
};

const initialSession = {
  id: sessionId,
  title: "Streaming review",
  title_status: "generated",
  created_at: "2026-05-03T12:00:00Z",
  updated_at: "2026-05-03T12:00:00Z",
  last_message_at: null,
  messages: []
};

const indexedDocument = documentRecord("completed-source.md", "text/markdown", "completed");
const pendingDocument = documentRecord("queued-source.md", "text/markdown", "queued");
const failedDocument = documentRecord("failed-source.pdf", "application/pdf", "failed");

test("chat composer streams answers, no-source responses, and citation cards", async ({ page }) => {
  const streamRequest = {
    method: "POST",
    path: `/api/chat/sessions/${sessionId}/messages/stream`,
    session_id: sessionId,
    body: { content: "When does escalation happen?" }
  };
  const delta = { text: "Escalation must happen " };
  const final = {
    assistant_message_id: sourceAssistantId,
    session_id: sessionId,
    sources: [source],
    model: "test-chat-model",
    usage: { requests: 1 }
  };
  const noSourceFinal = {
    assistant_message_id: noSourceAssistantId,
    session_id: sessionId,
    sources: [],
    model: "test-chat-model",
    usage: null
  };

  expectValueMatchesSchema(streamRequest, readSchema(schemaPaths.chatMessageStreamRequest));
  expectValueMatchesSchema(delta, readSchema(schemaPaths.chatMessageStreamDelta));
  expectValueMatchesSchema(final, readSchema(schemaPaths.chatMessageStreamFinal));

  let currentSession: {
    id: string;
    title: string;
    title_status: string;
    created_at: string;
    updated_at: string;
    last_message_at: string | null;
    messages: ReturnType<typeof message>[];
  } = initialSession;

  await page.route(`**/api/chat/sessions/${sessionId}`, async (route) => {
    await route.fulfill({ json: currentSession });
  });

  await page.route("**/api/chat/sessions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        json: [
          {
            ...initialSession,
            last_message: null
          }
        ]
      });
      return;
    }

    await route.fallback();
  });

  await routeDocuments(page, [indexedDocument]);

  await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, async (route) => {
    const body = route.request().postDataJSON() as { content: string };

    if (body.content.includes("unlisted")) {
      currentSession = {
        ...currentSession,
        messages: [
          ...currentSession.messages,
          message("user", body.content),
          message(
            "assistant",
            "I could not find relevant sources in the uploaded documents to answer that.",
            {
              id: noSourceAssistantId
            }
          )
        ]
      };
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          [
            "delta",
            { text: "I could not find relevant sources in the uploaded documents to answer that." }
          ],
          ["final", noSourceFinal]
        ])
      });
      return;
    }

    currentSession = {
      ...currentSession,
      messages: [
        ...currentSession.messages,
        message("user", body.content),
        message("assistant", "Escalation must happen within two days.", {
          id: sourceAssistantId,
          model: "test-chat-model",
          usage: { requests: 1 },
          sources: [source]
        })
      ]
    };
    await route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        ["delta", delta],
        ["delta", { text: "within two days." }],
        ["final", final]
      ])
    });
  });

  await page.goto("/?workspace-preview=1");

  const composer = page.getByPlaceholder(
    "Ask about your documents, code, or architecture specs..."
  );
  await expect(page.getByRole("heading", { name: "Streaming review" })).toBeVisible();
  await expect(page.getByText("Indexed sources available")).toBeVisible();
  await expect(composer).toBeEnabled();

  await composer.fill(streamRequest.body.content);
  await page.getByRole("button", { name: "Send" }).click();

  await expect(
    page.locator("article", { hasText: "Escalation must happen within two days." })
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Citations" })).toBeVisible();
  await expect(
    page.getByText("Source 1 / Escalation Runbook.md / Escalation / page 2")
  ).toBeVisible();
  await expect(
    page.locator(".font-mono", { hasText: "Escalation must happen within two days." })
  ).toBeVisible();
  await expect(page.getByText(`document: ${source.document_name}`)).toBeVisible();

  await composer.fill("Can you answer an unlisted policy?");
  await page.getByRole("button", { name: "Send" }).click();

  const noSourceArticle = page.locator("article", {
    hasText: "I could not find relevant sources in the uploaded documents to answer that."
  });
  await expect(noSourceArticle).toBeVisible();
  await expect(page.getByText("No source citations were returned for this answer.")).toBeVisible();

  const [articleBox, composerBox] = await Promise.all([
    noSourceArticle.boundingBox(),
    page.locator(".rag-composer").boundingBox()
  ]);
  expect(articleBox, "latest assistant message should have a layout box").not.toBeNull();
  expect(composerBox, "chat composer should have a layout box").not.toBeNull();
  expect(articleBox!.y + articleBox!.height).toBeLessThanOrEqual(composerBox!.y - 8);
});

test("chat source readiness reflects document status without opening the document pool", async ({
  page
}) => {
  await routeEmptyChat(page);
  await routeDocuments(page, []);

  await page.goto("/?workspace-preview=1");

  await expect(page.getByText("No indexed sources available")).toBeVisible();
  await expect(
    page.getByText("Upload documents before expecting answers grounded in the shared pool.")
  ).toBeVisible();
});

test("chat source readiness shows pending, ready, mixed, and error states", async ({ page }) => {
  await routeEmptyChat(page);

  let documentsResponse: "pending" | "ready" | "mixed" | "error" = "pending";
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }

    if (documentsResponse === "error") {
      await route.fulfill({ status: 500, json: { detail: "document list failed" } });
      return;
    }

    const documents =
      documentsResponse === "pending"
        ? [pendingDocument]
        : documentsResponse === "ready"
          ? [indexedDocument]
          : [indexedDocument, pendingDocument, failedDocument];
    await route.fulfill({ json: documents });
  });

  await page.goto("/?workspace-preview=1");

  await expect(page.getByText("Sources pending ingestion")).toBeVisible();
  await expect(page.getByText("Grounded answers are not ready yet.")).toBeVisible();

  documentsResponse = "ready";
  await page.getByRole("button", { name: "Document Pools" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button", { name: "Chat History" }).click();
  await expect(page.getByText("Indexed sources available")).toBeVisible();
  await expect(page.getByText("can ground new answers.")).toBeVisible();

  documentsResponse = "mixed";
  await page.getByRole("button", { name: "Document Pools" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button", { name: "Chat History" }).click();
  await expect(page.getByText("Indexed sources available with pending work")).toBeVisible();
  await expect(page.getByText("can ground answers; 1 pending and 1 failed.")).toBeVisible();

  documentsResponse = "error";
  await page.getByRole("button", { name: "Document Pools" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button", { name: "Chat History" }).click();
  await expect(page.getByText("Source status unavailable")).toBeVisible();
  await expect(page.getByText("grounding availability is unknown")).toBeVisible();
});

test("document status polling stops after pending documents become indexed", async ({ page }) => {
  await routeEmptyChat(page);

  let documentRequests = 0;
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }

    documentRequests += 1;
    await route.fulfill({ json: documentRequests === 1 ? [pendingDocument] : [indexedDocument] });
  });

  await page.goto("/?workspace-preview=1");

  await expect(page.getByText("Sources pending ingestion")).toBeVisible();
  await expect(page.getByText("Indexed sources available")).toBeVisible({ timeout: 7_000 });
  expect(documentRequests).toBe(2);

  await page.waitForTimeout(5_500);
  expect(documentRequests).toBe(2);
});

function message(
  role: "user" | "assistant",
  content: string,
  overrides: Partial<{
    id: string;
    model: string | null;
    usage: Record<string, unknown> | null;
    sources: (typeof source)[];
  }> = {}
) {
  return {
    id: overrides.id ?? crypto.randomUUID(),
    role,
    content,
    status: "completed",
    created_at: "2026-05-03T12:01:00Z",
    model: overrides.model ?? null,
    retrieval_query: null,
    usage: overrides.usage ?? null,
    sources: overrides.sources ?? []
  };
}

function sse(events: Array<[string, unknown]>) {
  return events
    .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

async function routeEmptyChat(page: Page) {
  await page.route("**/api/chat/sessions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }

    await route.fallback();
  });
}

async function routeDocuments(page: Page, documents: ReturnType<typeof documentRecord>[]) {
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: documents });
      return;
    }

    await route.fallback();
  });
}

function documentRecord(filename: string, mediaType: string, status: string) {
  return {
    id: crypto.randomUUID(),
    filename,
    media_type: mediaType,
    byte_size: 1024,
    status,
    uploaded_by: {
      id: "12121212-1212-1212-1212-121212121212",
      email: "sources@example.com",
      first_name: "Source",
      last_name: "Owner"
    },
    uploaded_at: "2026-05-03T12:00:00Z",
    deleted: false,
    deleted_at: null,
    failure_reason: status === "failed" ? "No extractable text was found." : null
  };
}
