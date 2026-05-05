import { expect, test } from "@playwright/test";

import { schemaPaths } from "./schema-paths";
import { expectValueMatchesSchema, readSchema, schemaFromValue, writeSchema } from "./schema-utils";

test("captures real chat session API schemas when a backend bearer token is available", async ({
  request
}) => {
  test.skip(
    !process.env.E2E_CHAT_BEARER_TOKEN,
    "Set E2E_CHAT_BEARER_TOKEN for real chat session API schema capture."
  );

  const headers = {
    Authorization: `Bearer ${process.env.E2E_CHAT_BEARER_TOKEN}`
  };

  const listResponse = await request.get(`${apiBaseUrl()}/api/chat/sessions`, { headers });
  await expectJsonOk(listResponse, "GET /api/chat/sessions");
  await assertOrWriteSchema(schemaPaths.chatSessionsList, await listResponse.json());

  await assertOrWriteSchema(schemaPaths.chatSessionCreateRequest, {
    method: "POST",
    path: "/api/chat/sessions"
  });
  const createResponse = await request.post(`${apiBaseUrl()}/api/chat/sessions`, { headers });
  await expectJsonOk(createResponse, "POST /api/chat/sessions");
  const created = await createResponse.json();
  await assertOrWriteSchema(schemaPaths.chatSessionCreate, created);

  await assertOrWriteSchema(schemaPaths.chatSessionLoadRequest, {
    method: "GET",
    path: `/api/chat/sessions/${created.id}`,
    session_id: created.id
  });
  const loadResponse = await request.get(`${apiBaseUrl()}/api/chat/sessions/${created.id}`, {
    headers
  });
  await expectJsonOk(loadResponse, "GET /api/chat/sessions/{id}");
  await assertOrWriteSchema(schemaPaths.chatSessionLoad, await loadResponse.json());
});

test("captures real streaming chat event schemas when model configuration is available", async ({
  request
}) => {
  test.skip(
    !process.env.E2E_CHAT_BEARER_TOKEN || process.env.E2E_CAPTURE_CHAT_STREAM !== "1",
    "Set E2E_CHAT_BEARER_TOKEN and E2E_CAPTURE_CHAT_STREAM=1 after backend model config is available."
  );

  const headers = {
    Authorization: `Bearer ${process.env.E2E_CHAT_BEARER_TOKEN}`
  };
  const createResponse = await request.post(`${apiBaseUrl()}/api/chat/sessions`, { headers });
  await expectJsonOk(createResponse, "POST /api/chat/sessions");
  const created = await createResponse.json();
  const content =
    process.env.E2E_CHAT_STREAM_CONTENT ?? "Answer briefly using the available document sources.";
  const streamRequest = {
    method: "POST",
    path: `/api/chat/sessions/${created.id}/messages/stream`,
    session_id: created.id,
    body: { content }
  };
  await assertOrWriteSchema(schemaPaths.chatMessageStreamRequest, streamRequest);

  const streamResponse = await request.post(
    `${apiBaseUrl()}/api/chat/sessions/${created.id}/messages/stream`,
    {
      headers,
      data: { content }
    }
  );
  await expectJsonOk(streamResponse, "POST /api/chat/sessions/{id}/messages/stream");
  const events = parseSseEvents(await streamResponse.text());
  const delta = events.find((event) => event.event === "delta")?.data;
  const final = events.find((event) => event.event === "final")?.data;
  const error = events.find((event) => event.event === "error")?.data;

  if (delta) {
    await assertOrWriteSchema(schemaPaths.chatMessageStreamDelta, delta);
  }
  if (final) {
    await assertOrWriteSchema(schemaPaths.chatMessageStreamFinal, final);
  }
  if (error) {
    await assertOrWriteSchema(schemaPaths.chatMessageStreamError, error);
  }
});

async function assertOrWriteSchema(relativePath: string, value: unknown) {
  const schema = schemaFromValue(value);
  if (process.env.E2E_WRITE_SCHEMAS === "1") {
    writeSchema(relativePath, schema);
    return;
  }

  expectValueMatchesSchema(value, readSchema(relativePath));
}

function apiBaseUrl() {
  return (process.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

async function expectJsonOk(
  response: { ok(): boolean; status(): number; text(): Promise<string> },
  label: string
) {
  if (response.ok()) {
    return;
  }

  expect(
    response.ok(),
    `${label} failed with ${response.status()}: ${(await response.text()).slice(0, 500)}`
  ).toBe(true);
}

function parseSseEvents(text: string) {
  return text
    .trim()
    .split("\n\n")
    .filter(Boolean)
    .map((rawEvent) => {
      const lines = rawEvent.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event: "))?.slice("event: ".length);
      const data = lines
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice("data: ".length))
        .join("\n");

      return {
        event,
        data: JSON.parse(data) as unknown
      };
    });
}
