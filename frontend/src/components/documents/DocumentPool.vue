<script setup lang="ts">
import { FileText, RefreshCw, Search, Upload } from "lucide-vue-next";
import { ref } from "vue";

import type { DocumentRecord } from "../../lib/api";
import {
  type DocumentTypeFilter,
  type DocumentsStatus,
  documentTypeFilters,
  documentTypeLabel,
  formatBytes,
  formatDate,
  statusClass,
  statusLabel,
  uploaderLabel
} from "../../composables/useDocuments";

defineProps<{
  activeCount: number;
  deletingDocumentIds: Set<string>;
  documents: DocumentRecord[];
  documentsMessage: string;
  documentsStatus: DocumentsStatus;
  documentPendingDelete: DocumentRecord | null;
  filteredDocuments: DocumentRecord[];
  indexedDocuments: number;
  queuedDocuments: number;
  storageUsed: string;
  uploadStatus: "idle" | "uploading";
}>();

const documentSearchQuery = defineModel<string>("documentSearchQuery", { required: true });
const documentTypeFilter = defineModel<DocumentTypeFilter>("documentTypeFilter", {
  required: true
});

const emit = defineEmits<{
  cancelDelete: [];
  confirmDelete: [];
  refresh: [];
  requestDelete: [document: DocumentRecord];
  upload: [file: File];
}>();

const fileInput = ref<HTMLInputElement | null>(null);

function openFilePicker() {
  fileInput.value?.click();
}

function handleFileSelected(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";

  if (file) {
    emit("upload", file);
  }
}
</script>

<template>
  <section class="mx-auto w-full max-w-6xl">
    <div class="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h1 class="text-4xl font-bold tracking-tight text-[#181a2a]">Document Pools</h1>
        <p class="mt-2 text-lg text-[#404751]">
          Shared document upload, status review, and deletion.
        </p>
      </div>
      <input
        ref="fileInput"
        class="hidden"
        type="file"
        accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
        @change="handleFileSelected"
      />
      <button
        class="btn border-0 bg-[#0082ce] text-white hover:bg-[#00609a]"
        :disabled="uploadStatus === 'uploading'"
        type="button"
        @click="openFilePicker"
      >
        <span v-if="uploadStatus === 'uploading'" class="loading loading-spinner loading-sm"></span>
        <Upload :size="18" />
        Upload Document
      </button>
    </div>

    <div class="mb-8 grid gap-6 md:grid-cols-3">
      <div class="stats rounded-lg border border-[#d1d1d1] bg-white shadow-none">
        <div class="stat">
          <div class="stat-title uppercase tracking-wider text-[#404751]">Total Indexed</div>
          <div class="stat-value text-[#181a2a]">{{ indexedDocuments }}</div>
          <div class="stat-desc text-[#006a61]">Completed ingestion status only</div>
        </div>
      </div>
      <div class="stats rounded-lg border border-[#d1d1d1] bg-white shadow-none">
        <div class="stat">
          <div class="stat-title uppercase tracking-wider text-[#404751]">Storage Used</div>
          <div class="stat-value text-[#181a2a]">{{ storageUsed }}</div>
          <div class="stat-desc text-[#404751]">Active shared files</div>
        </div>
      </div>
      <div class="stats rounded-lg border border-[#d1d1d1] bg-white shadow-none">
        <div class="stat">
          <div class="stat-title uppercase tracking-wider text-[#404751]">Processing Queue</div>
          <div class="stat-value text-[#181a2a]">{{ queuedDocuments }}</div>
          <div class="stat-desc text-[#b15f00]">Worker behavior is outside this task</div>
        </div>
      </div>
    </div>

    <div class="mb-4 flex flex-col gap-3 rounded-lg border border-[#d1d1d1] bg-white p-3">
      <div class="flex flex-wrap items-center justify-between gap-3 text-sm text-[#404751]">
        <span>{{ documentsMessage }}</span>
        <button
          class="btn btn-ghost btn-sm"
          :disabled="documentsStatus === 'loading'"
          type="button"
          @click="emit('refresh')"
        >
          <span
            v-if="documentsStatus === 'loading'"
            class="loading loading-spinner loading-xs"
          ></span>
          <RefreshCw v-else :size="16" />
          Refresh
        </button>
      </div>
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div class="join">
          <button
            v-for="filter in documentTypeFilters"
            :key="filter.value"
            class="btn join-item btn-sm"
            :class="
              documentTypeFilter === filter.value
                ? 'border-0 bg-[#0082ce] text-white hover:bg-[#00609a]'
                : 'border-[#d1d1d1] bg-white text-[#181a2a]'
            "
            type="button"
            @click="documentTypeFilter = filter.value"
          >
            {{ filter.label }}
          </button>
        </div>
        <label
          class="input input-sm input-bordered flex w-full items-center gap-2 rounded border-[#d1d1d1] bg-white lg:max-w-sm"
        >
          <Search class="text-slate-400" :size="16" />
          <input
            v-model="documentSearchQuery"
            class="grow"
            type="search"
            placeholder="Search visible metadata..."
          />
        </label>
      </div>
    </div>

    <div class="overflow-x-auto overflow-y-hidden rounded-lg border border-[#d1d1d1] bg-white">
      <table class="table min-w-[720px]">
        <thead
          class="border-b border-[#d1d1d1] bg-white text-xs uppercase tracking-wider text-[#404751]"
        >
          <tr>
            <th>Document Name</th>
            <th class="text-right">Size</th>
            <th class="text-center">Status</th>
            <th class="text-right">Date Added</th>
            <th class="text-right">Delete</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="documentsStatus === 'loading'">
            <td colspan="5" class="py-10 text-center text-[#404751]">
              <span class="loading loading-spinner loading-sm mr-2"></span>
              Loading documents
            </td>
          </tr>
          <tr v-else-if="documents.length === 0">
            <td colspan="5" class="py-10 text-center text-[#404751]">
              No active documents are available. Upload a .txt, .md, or .pdf file to start the
              shared pool.
            </td>
          </tr>
          <tr v-else-if="filteredDocuments.length === 0">
            <td colspan="5" class="py-10 text-center text-[#404751]">
              No documents match the selected type or visible metadata search.
            </td>
          </tr>
          <template v-else>
            <tr
              v-for="document in filteredDocuments"
              :key="document.id"
              :class="{ 'opacity-70': document.deleted }"
            >
              <td>
                <div class="flex items-center gap-3">
                  <div class="grid h-9 w-9 place-items-center rounded bg-blue-50 text-[#0082ce]">
                    <FileText :size="18" />
                  </div>
                  <div class="min-w-0">
                    <p class="truncate font-medium text-[#181a2a]">{{ document.filename }}</p>
                    <p class="break-all font-mono text-xs text-[#404751]">id: {{ document.id }}</p>
                    <p class="text-xs text-[#404751]">
                      {{ documentTypeLabel(document) }} / {{ document.media_type }}
                    </p>
                    <p class="text-xs text-[#404751]">Uploaded by {{ uploaderLabel(document) }}</p>
                    <p v-if="document.failure_reason" class="text-xs text-[#ba1a1a]">
                      {{ document.failure_reason }}
                    </p>
                  </div>
                </div>
              </td>
              <td class="text-right font-mono text-[#404751]">
                {{ formatBytes(document.byte_size) }}
              </td>
              <td class="text-center">
                <span class="badge rounded-full" :class="statusClass(document)">
                  {{ statusLabel(document) }}
                </span>
              </td>
              <td class="text-right text-[#404751]">
                <span>{{ formatDate(document.uploaded_at) }}</span>
                <span v-if="document.deleted_at" class="block text-xs">
                  Deleted {{ formatDate(document.deleted_at) }}
                </span>
              </td>
              <td class="text-right">
                <button
                  class="btn btn-outline btn-sm border-[#ba1a1a] text-[#ba1a1a]"
                  :disabled="document.deleted || deletingDocumentIds.has(document.id)"
                  type="button"
                  @click="emit('requestDelete', document)"
                >
                  <span
                    v-if="deletingDocumentIds.has(document.id)"
                    class="loading loading-spinner loading-xs"
                  ></span>
                  Delete for everyone
                </button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div
        class="flex items-center justify-between border-t border-[#d1d1d1] px-6 py-3 text-sm text-[#404751]"
      >
        <span
          >Any authenticated user can delete any shared document. Deleted rows are excluded by
          backend list responses.</span
        >
        <span>{{ activeCount }} active</span>
      </div>
    </div>

    <div
      v-if="documentPendingDelete"
      class="fixed inset-0 z-50 grid place-items-center bg-black/45 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="document-delete-title"
    >
      <div class="w-full max-w-lg rounded-lg border border-[#d1d1d1] bg-white p-6 shadow-xl">
        <p class="text-xs font-semibold uppercase tracking-wider text-[#ba1a1a]">
          Shared document deletion
        </p>
        <h2 id="document-delete-title" class="mt-2 text-2xl font-bold text-[#181a2a]">
          Delete {{ documentPendingDelete.filename }}?
        </h2>
        <p class="mt-3 text-sm leading-6 text-[#404751]">
          This removes the document from the shared pool for every authenticated user. Existing
          answers may still reference prior citations, but new retrieval should no longer use this
          source.
        </p>
        <div class="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            class="btn border-[#d1d1d1] bg-white text-[#181a2a]"
            type="button"
            @click="emit('cancelDelete')"
          >
            Cancel
          </button>
          <button
            class="btn border-0 bg-[#ba1a1a] text-white hover:bg-[#941313]"
            type="button"
            @click="emit('confirmDelete')"
          >
            Delete for everyone
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
