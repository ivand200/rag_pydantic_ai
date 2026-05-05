import { describe, expect, it } from "vitest";

import type { DocumentRecord } from "../lib/api";
import {
  documentSearchFields,
  documentTypeLabel,
  formatBytes,
  statusLabel,
  uploaderLabel
} from "./useDocuments";

const baseDocument: DocumentRecord = {
  id: "document-id",
  filename: "runbook.md",
  media_type: "text/markdown",
  byte_size: 1536,
  status: "completed",
  uploaded_by: {
    id: "user-id",
    email: "owner@example.com",
    first_name: "Owner",
    last_name: "User"
  },
  uploaded_at: "2026-05-03T10:00:00Z",
  deleted: false,
  deleted_at: null,
  failure_reason: null
};

describe("document view helpers", () => {
  it("formats document metadata used by filters and visible table fields", () => {
    expect(documentTypeLabel(baseDocument)).toBe("Markdown");
    expect(statusLabel(baseDocument)).toBe("Ready");
    expect(formatBytes(baseDocument.byte_size)).toBe("1.5 KB");
    expect(uploaderLabel(baseDocument)).toBe("owner@example.com");
  });

  it("keeps visible search fields aligned with shared document metadata", () => {
    const fields = documentSearchFields({
      ...baseDocument,
      filename: "failed-policy.pdf",
      media_type: "application/pdf",
      status: "failed",
      failure_reason: "No extractable text was found."
    });

    expect(fields).toContain("failed-policy.pdf");
    expect(fields).toContain("PDF");
    expect(fields).toContain("Failed");
    expect(fields).toContain("owner@example.com");
    expect(fields).toContain("No extractable text was found.");
  });
});
