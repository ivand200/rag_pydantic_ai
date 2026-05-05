import { expect, test } from "@playwright/test";

import { schemaPaths } from "./schema-paths";
import { expectValueMatchesSchema, readSchema, schemaFromValue, writeSchema } from "./schema-utils";

test("captures real document API schemas when a backend bearer token is available", async ({
  request
}) => {
  test.skip(
    !process.env.E2E_DOCUMENT_BEARER_TOKEN,
    "Set E2E_DOCUMENT_BEARER_TOKEN for real document API schema capture."
  );

  const headers = {
    Authorization: `Bearer ${process.env.E2E_DOCUMENT_BEARER_TOKEN}`
  };

  const listResponse = await request.get(`${apiBaseUrl()}/api/documents`, { headers });
  await expectJsonOk(listResponse, "GET /api/documents");
  await assertOrWriteSchema(schemaPaths.documentsList, await listResponse.json());

  const uploadResponse = await request.post(`${apiBaseUrl()}/api/documents`, {
    headers,
    multipart: {
      file: {
        name: "document-schema-capture.md",
        mimeType: "text/markdown",
        buffer: Buffer.from("# Document schema capture\n")
      }
    }
  });
  await assertOrWriteSchema(schemaPaths.documentUploadRequest, {
    method: "POST",
    path: "/api/documents",
    content_type: "multipart/form-data",
    fields: {
      file: {
        filename: "document-schema-capture.md",
        media_type: "text/markdown"
      }
    }
  });
  await expectJsonOk(uploadResponse, "POST /api/documents");
  const uploaded = await uploadResponse.json();
  await assertOrWriteSchema(schemaPaths.documentUpload, uploaded);

  const deleteResponse = await request.delete(`${apiBaseUrl()}/api/documents/${uploaded.id}`, {
    headers
  });
  await assertOrWriteSchema(schemaPaths.documentDeleteRequest, {
    method: "DELETE",
    path: `/api/documents/${uploaded.id}`,
    document_id: uploaded.id
  });
  await expectJsonOk(deleteResponse, "DELETE /api/documents/{id}");
  await assertOrWriteSchema(schemaPaths.documentDelete, await deleteResponse.json());
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
