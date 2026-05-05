import { expect, test } from "@playwright/test";

import { schemaPaths } from "./schema-paths";
import { expectValueMatchesSchema, readSchema } from "./schema-utils";

const uploadedBy = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "owner@example.com",
  first_name: "Shared",
  last_name: "Owner"
};

const textUploader = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  email: "writer@example.com",
  first_name: "Text",
  last_name: "Writer"
};

const initialDocuments = [
  {
    id: "22222222-2222-2222-2222-222222222222",
    filename: "processing-runbook.md",
    media_type: "text/markdown",
    byte_size: 2048,
    status: "processing",
    uploaded_by: uploadedBy,
    uploaded_at: "2026-05-03T10:00:00Z",
    deleted: false,
    deleted_at: null,
    failure_reason: null
  },
  {
    id: "55555555-5555-5555-5555-555555555555",
    filename: "architecture-notes.txt",
    media_type: "application/octet-stream",
    byte_size: 1024,
    status: "completed",
    uploaded_by: textUploader,
    uploaded_at: "2026-05-03T09:55:00Z",
    deleted: false,
    deleted_at: null,
    failure_reason: null
  },
  {
    id: "33333333-3333-3333-3333-333333333333",
    filename: "failed-on-ingestion.pdf",
    media_type: "application/pdf",
    byte_size: 4096,
    status: "failed",
    uploaded_by: uploadedBy,
    uploaded_at: "2026-05-03T09:45:00Z",
    deleted: false,
    deleted_at: null,
    failure_reason: "No extractable text was found."
  }
];

const uploadedDocument = {
  id: "44444444-4444-4444-4444-444444444444",
  filename: "task4-notes.md",
  media_type: "text/markdown",
  byte_size: 18,
  status: "queued",
  uploaded_by: uploadedBy,
  uploaded_at: "2026-05-03T10:15:00Z",
  deleted: false,
  deleted_at: null,
  failure_reason: null
};

const uploadRequest = {
  method: "POST",
  path: "/api/documents",
  content_type: "multipart/form-data",
  fields: {
    file: {
      filename: uploadedDocument.filename,
      media_type: uploadedDocument.media_type
    }
  }
};

const deleteRequest = {
  method: "DELETE",
  path: `/api/documents/${uploadedDocument.id}`,
  document_id: uploadedDocument.id
};

test("document pool requires shared-pool confirmation before deleting a document", async ({
  page
}) => {
  expectValueMatchesSchema(initialDocuments, readSchema(schemaPaths.documentsList));
  expectValueMatchesSchema(uploadRequest, readSchema(schemaPaths.documentUploadRequest));
  expectValueMatchesSchema(uploadedDocument, readSchema(schemaPaths.documentUpload));
  expectValueMatchesSchema(deleteRequest, readSchema(schemaPaths.documentDeleteRequest));

  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: initialDocuments });
      return;
    }

    if (route.request().method() === "POST") {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data");
      await route.fulfill({ status: 201, json: uploadedDocument });
      return;
    }

    await route.fallback();
  });

  let deleteRequestCount = 0;

  await page.route(`**/api/documents/${uploadedDocument.id}`, async (route) => {
    deleteRequestCount += 1;
    expect(route.request().method()).toBe(deleteRequest.method);
    const deletedDocument = {
      ...uploadedDocument,
      deleted: true,
      deleted_at: "2026-05-03T10:20:00Z"
    };
    expectValueMatchesSchema(deletedDocument, readSchema(schemaPaths.documentDelete));
    await route.fulfill({ json: deletedDocument });
  });

  await page.goto("/?workspace-preview=1");
  await page.getByRole("button", { name: "Document Pools" }).click();

  const processingRow = page.locator("tr", { hasText: "processing-runbook.md" });
  await expect(processingRow).toBeVisible();
  await expect(processingRow.getByText("Processing", { exact: true })).toBeVisible();
  await expect(page.getByText("failed-on-ingestion.pdf")).toBeVisible();
  await expect(page.getByText("No extractable text was found.")).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: uploadedDocument.filename,
    mimeType: uploadedDocument.media_type,
    buffer: Buffer.from("Task 4 smoke notes")
  });

  const uploadedRow = page.locator("tr", { hasText: uploadedDocument.filename });
  await expect(uploadedRow.getByText(uploadedDocument.filename, { exact: true })).toBeVisible();
  await expect(uploadedRow.getByText("Queued", { exact: true })).toBeVisible();

  const deleteButton = uploadedRow.getByRole("button", { name: "Delete for everyone" });

  await deleteButton.click();

  const confirmation = page.getByRole("dialog", { name: `Delete ${uploadedDocument.filename}?` });
  await expect(confirmation).toBeVisible();
  await expect(confirmation.getByText(uploadedDocument.filename)).toBeVisible();
  await expect(confirmation.getByText("shared pool for every authenticated user")).toBeVisible();
  expect(deleteRequestCount).toBe(0);

  await confirmation.getByRole("button", { name: "Cancel" }).click();

  await expect(confirmation).toHaveCount(0);
  expect(deleteRequestCount).toBe(0);
  await expect(uploadedRow.getByText("Queued", { exact: true })).toBeVisible();

  await deleteButton.click();
  await page
    .getByRole("dialog", { name: `Delete ${uploadedDocument.filename}?` })
    .getByRole("button", { name: "Delete for everyone" })
    .click();

  await expect(uploadedRow.getByText("Deleted", { exact: true })).toBeVisible();
  expect(deleteRequestCount).toBe(1);
  await expect(uploadedRow.getByRole("button", { name: "Delete for everyone" })).toBeDisabled();
  await expect(
    page.getByText("Any authenticated user can delete any shared document.")
  ).toBeVisible();
});

test("document pool filters by type and searches visible metadata", async ({ page }) => {
  expectValueMatchesSchema(initialDocuments, readSchema(schemaPaths.documentsList));

  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: initialDocuments });
      return;
    }

    await route.fallback();
  });

  await page.goto("/?workspace-preview=1");
  await page.getByRole("button", { name: "Document Pools" }).click();

  const markdownRow = page.locator("tr", { hasText: "processing-runbook.md" });
  const textRow = page.locator("tr", { hasText: "architecture-notes.txt" });
  const pdfRow = page.locator("tr", { hasText: "failed-on-ingestion.pdf" });
  const search = page.getByPlaceholder("Search visible metadata...");

  await expect(markdownRow).toBeVisible();
  await expect(textRow).toBeVisible();
  await expect(textRow.getByText("Text / application/octet-stream")).toBeVisible();
  await expect(pdfRow).toBeVisible();

  await page.getByRole("button", { name: "PDF", exact: true }).click();
  await expect(pdfRow).toBeVisible();
  await expect(markdownRow).toHaveCount(0);
  await expect(textRow).toHaveCount(0);

  await page.getByRole("button", { name: "Text", exact: true }).click();
  await expect(textRow).toBeVisible();
  await expect(markdownRow).toHaveCount(0);
  await expect(pdfRow).toHaveCount(0);

  await page.getByRole("button", { name: "Markdown", exact: true }).click();
  await expect(markdownRow).toBeVisible();
  await expect(textRow).toHaveCount(0);
  await expect(pdfRow).toHaveCount(0);

  await page.getByRole("button", { name: "All", exact: true }).click();
  await search.fill("writer@example.com");
  await expect(textRow).toBeVisible();
  await expect(markdownRow).toHaveCount(0);
  await expect(pdfRow).toHaveCount(0);

  await search.fill("failed");
  await expect(pdfRow).toBeVisible();
  await expect(markdownRow).toHaveCount(0);
  await expect(textRow).toHaveCount(0);

  await search.fill("no matching visible metadata");
  await expect(
    page.getByText("No documents match the selected type or visible metadata search.")
  ).toBeVisible();
  await expect(page.getByText("full-text")).toHaveCount(0);
  await expect(page.getByText("document contents")).toHaveCount(0);
});
