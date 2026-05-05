import { computed, onBeforeUnmount, ref, watch } from "vue";

import {
  type ClerkTokenProvider,
  type DocumentRecord,
  deleteDocument,
  fetchDocuments,
  uploadDocument
} from "../lib/api";

export type DocumentsStatus = "idle" | "loading" | "ready" | "error";
export type DocumentTypeFilter = "all" | "pdf" | "text" | "markdown";
export type SourceReadinessTone = "loading" | "error" | "empty" | "pending" | "ready" | "mixed";

export const documentTypeFilters: Array<{ value: DocumentTypeFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "pdf", label: "PDF" },
  { value: "text", label: "Text" },
  { value: "markdown", label: "Markdown" }
];

export function useDocuments(options: {
  getBackendToken: ClerkTokenProvider | null;
  isSignedInForWorkspace: () => boolean;
}) {
  const documents = ref<DocumentRecord[]>([]);
  const documentsStatus = ref<DocumentsStatus>("idle");
  const documentsMessage = ref("Open the document pool to load shared documents.");
  const uploadStatus = ref<"idle" | "uploading">("idle");
  const deletingDocumentIds = ref(new Set<string>());
  const documentPendingDelete = ref<DocumentRecord | null>(null);
  const documentTypeFilter = ref<DocumentTypeFilter>("all");
  const documentSearchQuery = ref("");
  const documentsRefreshInFlight = ref(false);
  const documentPollingInterval = ref<ReturnType<typeof window.setInterval> | null>(null);

  const activeDocuments = computed(() => documents.value.filter((document) => !document.deleted));
  const indexedDocuments = computed(
    () => activeDocuments.value.filter((document) => document.status === "completed").length
  );
  const queuedDocuments = computed(
    () =>
      activeDocuments.value.filter((document) => ["queued", "processing"].includes(document.status))
        .length
  );
  const failedDocuments = computed(
    () => activeDocuments.value.filter((document) => document.status === "failed").length
  );
  const shouldPollDocuments = computed(() => queuedDocuments.value > 0);
  const storageUsed = computed(() =>
    formatBytes(activeDocuments.value.reduce((total, document) => total + document.byte_size, 0))
  );
  const filteredDocuments = computed(() => {
    const query = documentSearchQuery.value.trim().toLowerCase();

    return documents.value.filter((document) => {
      if (
        documentTypeFilter.value !== "all" &&
        documentType(document) !== documentTypeFilter.value
      ) {
        return false;
      }

      if (!query) {
        return true;
      }

      return documentSearchFields(document).some((field) => field.toLowerCase().includes(query));
    });
  });

  const sourceReadiness = computed(
    (): { tone: SourceReadinessTone; title: string; message: string } => {
      if (documentsStatus.value === "loading" || documentsStatus.value === "idle") {
        return {
          tone: "loading",
          title: "Checking source readiness",
          message: "Loading shared document status before reporting grounded source availability."
        };
      }

      if (documentsStatus.value === "error") {
        return {
          tone: "error",
          title: "Source status unavailable",
          message: "Document status could not be loaded, so grounding availability is unknown."
        };
      }

      if (activeDocuments.value.length === 0) {
        return {
          tone: "empty",
          title: "No indexed sources available",
          message: "Upload documents before expecting answers grounded in the shared pool."
        };
      }

      if (indexedDocuments.value === 0 && queuedDocuments.value > 0) {
        return {
          tone: "pending",
          title: "Sources pending ingestion",
          message: `${queuedDocuments.value} document${queuedDocuments.value === 1 ? " is" : "s are"} queued or processing. Grounded answers are not ready yet.`
        };
      }

      if (indexedDocuments.value > 0 && (queuedDocuments.value > 0 || failedDocuments.value > 0)) {
        return {
          tone: "mixed",
          title: "Indexed sources available with pending work",
          message: `${indexedDocuments.value} indexed document${indexedDocuments.value === 1 ? "" : "s"} can ground answers; ${queuedDocuments.value} pending and ${failedDocuments.value} failed.`
        };
      }

      if (indexedDocuments.value > 0) {
        return {
          tone: "ready",
          title: "Indexed sources available",
          message: `${indexedDocuments.value} indexed document${indexedDocuments.value === 1 ? "" : "s"} can ground new answers.`
        };
      }

      return {
        tone: "empty",
        title: "No indexed sources available",
        message: "Active documents are present, but none are indexed for grounded answers."
      };
    }
  );

  async function refreshDocuments(options_: { preserveMessage?: boolean } = {}) {
    if (!options.getBackendToken) {
      documentsStatus.value = "error";
      if (!options_.preserveMessage) {
        documentsMessage.value = "Sign in is required before loading documents.";
      }
      return;
    }

    if (documentsRefreshInFlight.value) {
      return;
    }

    documentsRefreshInFlight.value = true;

    if (!options_.preserveMessage) {
      documentsStatus.value = "loading";
      documentsMessage.value = "Loading shared document pool...";
    } else if (documentsStatus.value === "idle") {
      documentsStatus.value = "loading";
    }

    try {
      documents.value = await fetchDocuments(options.getBackendToken);
      documentsStatus.value = "ready";
      if (!options_.preserveMessage) {
        documentsMessage.value =
          documents.value.length > 0
            ? "Shared document pool loaded from the backend."
            : "No active documents are in the shared pool.";
      }
    } catch (error) {
      documentsStatus.value = "error";
      if (!options_.preserveMessage) {
        documentsMessage.value =
          error instanceof Error ? error.message : "Document list request failed.";
      }
    } finally {
      documentsRefreshInFlight.value = false;
    }
  }

  async function uploadDocumentFile(file: File) {
    if (!options.getBackendToken) {
      return null;
    }

    uploadStatus.value = "uploading";
    documentsMessage.value = `Uploading ${file.name}...`;

    try {
      const uploaded = await uploadDocument(options.getBackendToken, file);
      documents.value = [
        uploaded,
        ...documents.value.filter((document) => document.id !== uploaded.id)
      ];
      documentsStatus.value = "ready";
      documentsMessage.value = `${uploaded.filename} uploaded and queued for ingestion.`;
      return uploaded;
    } catch (error) {
      documentsStatus.value = "error";
      documentsMessage.value = error instanceof Error ? error.message : "Document upload failed.";
      return null;
    } finally {
      uploadStatus.value = "idle";
    }
  }

  function requestDeleteDocument(document: DocumentRecord) {
    if (document.deleted || deletingDocumentIds.value.has(document.id)) {
      return;
    }

    documentPendingDelete.value = document;
  }

  function cancelDeleteDocument() {
    documentPendingDelete.value = null;
  }

  async function confirmDeleteDocument() {
    const document = documentPendingDelete.value;

    if (!options.getBackendToken || !document || document.deleted) {
      return;
    }

    documentPendingDelete.value = null;
    deletingDocumentIds.value = new Set(deletingDocumentIds.value).add(document.id);
    documentsMessage.value = `Deleting ${document.filename} for every user...`;

    try {
      const deleted = await deleteDocument(options.getBackendToken, document.id);
      documents.value = documents.value.map((current) =>
        current.id === deleted.id ? deleted : current
      );
      documentsStatus.value = "ready";
      documentsMessage.value = `${deleted.filename} is marked deleted for all users.`;
    } catch (error) {
      documentsStatus.value = "error";
      documentsMessage.value =
        error instanceof Error ? error.message : "Document delete request failed.";
    } finally {
      const nextDeletingIds = new Set(deletingDocumentIds.value);
      nextDeletingIds.delete(document.id);
      deletingDocumentIds.value = nextDeletingIds;
    }
  }

  function resetDocuments() {
    stopDocumentPolling();
    documents.value = [];
    documentsStatus.value = "idle";
    documentsMessage.value = "Open the document pool to load shared documents.";
    uploadStatus.value = "idle";
    deletingDocumentIds.value = new Set();
    documentPendingDelete.value = null;
    documentTypeFilter.value = "all";
    documentSearchQuery.value = "";
  }

  watch(
    () => [options.isSignedInForWorkspace(), shouldPollDocuments.value] as const,
    ([isSignedIn, shouldPoll]) => {
      if (isSignedIn && shouldPoll) {
        startDocumentPolling();
        return;
      }

      stopDocumentPolling();
    },
    { immediate: true }
  );

  onBeforeUnmount(() => {
    stopDocumentPolling();
  });

  function startDocumentPolling() {
    if (documentPollingInterval.value) {
      return;
    }

    documentPollingInterval.value = window.setInterval(() => {
      if (!options.isSignedInForWorkspace() || !shouldPollDocuments.value) {
        stopDocumentPolling();
        return;
      }

      void refreshDocuments({ preserveMessage: true });
    }, 5_000);
  }

  function stopDocumentPolling() {
    if (!documentPollingInterval.value) {
      return;
    }

    window.clearInterval(documentPollingInterval.value);
    documentPollingInterval.value = null;
  }

  return {
    activeDocuments,
    cancelDeleteDocument,
    confirmDeleteDocument,
    deletingDocumentIds,
    documentPendingDelete,
    documents,
    documentsMessage,
    documentsStatus,
    documentSearchQuery,
    documentTypeFilter,
    failedDocuments,
    filteredDocuments,
    indexedDocuments,
    refreshDocuments,
    requestDeleteDocument,
    resetDocuments,
    sourceReadiness,
    storageUsed,
    queuedDocuments,
    uploadDocumentFile,
    uploadStatus
  };
}

export function statusLabel(document: DocumentRecord) {
  if (document.deleted) {
    return "Deleted";
  }

  if (document.status === "queued") {
    return "Queued";
  }

  if (document.status === "processing") {
    return "Processing";
  }

  if (document.status === "completed") {
    return "Ready";
  }

  if (document.status === "failed") {
    return "Failed";
  }

  return document.status;
}

export function statusClass(document: DocumentRecord) {
  if (document.deleted) {
    return "border-[#404751] bg-white text-[#404751]";
  }

  if (document.status === "completed") {
    return "border-0 bg-[#009689] text-white";
  }

  if (document.status === "failed") {
    return "border-0 bg-[#ba1a1a] text-white";
  }

  return "border-[#0082ce] bg-white text-[#0082ce]";
}

export function documentType(document: DocumentRecord): Exclude<DocumentTypeFilter, "all"> {
  const mediaType = document.media_type.toLowerCase();
  const filename = document.filename.toLowerCase();

  if (mediaType.includes("pdf") || filename.endsWith(".pdf")) {
    return "pdf";
  }

  if (
    mediaType.includes("markdown") ||
    filename.endsWith(".md") ||
    filename.endsWith(".markdown")
  ) {
    return "markdown";
  }

  if (mediaType.startsWith("text/") || filename.endsWith(".txt")) {
    return "text";
  }

  return "text";
}

export function documentTypeLabel(document: DocumentRecord) {
  const type = documentType(document);

  if (type === "pdf") {
    return "PDF";
  }

  if (type === "markdown") {
    return "Markdown";
  }

  return "Text";
}

export function documentSearchFields(document: DocumentRecord) {
  return [
    document.filename,
    document.id,
    document.media_type,
    documentTypeLabel(document),
    statusLabel(document),
    uploaderLabel(document),
    document.failure_reason ?? "",
    formatBytes(document.byte_size),
    formatDate(document.uploaded_at),
    document.deleted_at ? formatDate(document.deleted_at) : ""
  ];
}

export function uploaderLabel(document: DocumentRecord) {
  return document.uploaded_by.email ?? document.uploaded_by.first_name ?? document.uploaded_by.id;
}

export function formatBytes(bytes: number) {
  if (bytes === 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`;
}

export function formatDate(value?: string | null) {
  if (!value) {
    return "Not returned";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
