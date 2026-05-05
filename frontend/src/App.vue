<script setup lang="ts">
import { useAuth } from "@clerk/vue";
import { ref, watch } from "vue";

import AccessGate from "./components/AccessGate.vue";
import WorkspaceShell from "./components/WorkspaceShell.vue";
import ChatComposer from "./components/chat/ChatComposer.vue";
import ChatWorkspace from "./components/chat/ChatWorkspace.vue";
import DocumentPool from "./components/documents/DocumentPool.vue";
import { useChatSessions } from "./composables/useChatSessions";
import { useDocuments } from "./composables/useDocuments";
import { type ApiStatus, type ClerkTokenProvider, fetchCurrentUser } from "./lib/api";

type WorkspaceSection = "chat" | "documents";

const isClerkConfigured = Boolean(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY);
const isDevelopment = import.meta.env.DEV;
const isWorkspacePreview =
  isDevelopment && new URLSearchParams(window.location.search).get("workspace-preview") === "1";
const canShowWorkspace = isClerkConfigured || isWorkspacePreview;
const auth = isClerkConfigured ? useAuth() : null;
const getBackendToken: ClerkTokenProvider | null = isWorkspacePreview
  ? async () => "workspace-preview-token"
  : auth
    ? () => auth.getToken.value()
    : null;
const activeSection = ref<WorkspaceSection>("chat");

const apiStatus = ref<ApiStatus>({
  state: "idle",
  message: "Backend identity has not been checked yet."
});

const {
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
} = useDocuments({
  getBackendToken,
  isSignedInForWorkspace
});

const {
  activeChatSession,
  canSendChatMessage,
  chatMessage,
  chatSessions,
  chatStatus,
  chatStreaming,
  composerContent,
  createNewChat,
  creatingChatSession,
  deleteChatSessionById,
  deletingChatSessionIds,
  loadChatSession,
  loadingChatSessionId,
  refreshChatSessions,
  selectedChatSessionId,
  sendChatMessage,
  streamingAssistantMessageId
} = useChatSessions({
  activateChat,
  getBackendToken,
  isSignedInForWorkspace
});

async function checkBackendIdentity() {
  if (!getBackendToken) {
    apiStatus.value = {
      state: "error",
      message: "Missing VITE_CLERK_PUBLISHABLE_KEY."
    };
    return;
  }

  apiStatus.value = {
    state: "loading",
    message: "Requesting protected identity from the backend..."
  };

  try {
    const currentUser = await fetchCurrentUser(getBackendToken);
    apiStatus.value = {
      state: "ready",
      message: "Backend synced the local app user.",
      user: currentUser
    };
  } catch (error) {
    apiStatus.value = {
      state: "error",
      message: error instanceof Error ? error.message : "Backend identity check failed."
    };
  }
}

async function handleUploadDocument(file: File) {
  const uploaded = await uploadDocumentFile(file);

  if (uploaded) {
    activeSection.value = "documents";
  }
}

function activateChat() {
  activeSection.value = "chat";
}

function isSignedInForWorkspace() {
  return isWorkspacePreview || (auth?.isSignedIn.value ?? false);
}

watch(activeSection, (section) => {
  if (section === "documents" && documentsStatus.value === "idle") {
    void refreshDocuments();
  }
});

watch(
  () => isSignedInForWorkspace(),
  (isSignedIn) => {
    if (isSignedIn && documentsStatus.value === "idle") {
      void refreshDocuments({ preserveMessage: true });
    }

    if (!isSignedIn && !isWorkspacePreview) {
      resetDocuments();
    }
  },
  { immediate: true }
);
</script>

<template>
  <main class="min-h-screen bg-base-200 text-base-content">
    <AccessGate :can-show-workspace="canShowWorkspace" :is-workspace-preview="isWorkspacePreview">
      <WorkspaceShell
        v-model:active-section="activeSection"
        :api-status="apiStatus"
        :chat-sessions="chatSessions"
        :chat-status="chatStatus"
        :creating-chat-session="creatingChatSession"
        :deleting-chat-session-ids="deletingChatSessionIds"
        :is-workspace-preview="isWorkspacePreview"
        :loading-chat-session-id="loadingChatSessionId"
        :selected-chat-session-id="selectedChatSessionId"
        @check-backend-identity="checkBackendIdentity"
        @delete-chat-session="deleteChatSessionById"
        @load-chat-session="loadChatSession"
        @new-chat="createNewChat"
        @refresh-chat-sessions="refreshChatSessions"
      >
        <ChatWorkspace
          v-if="activeSection === 'chat'"
          :active-chat-session="activeChatSession"
          :chat-message="chatMessage"
          :chat-status="chatStatus"
          :creating-chat-session="creatingChatSession"
          :failed-documents="failedDocuments"
          :indexed-documents="indexedDocuments"
          :queued-documents="queuedDocuments"
          :source-readiness="sourceReadiness"
          :streaming-assistant-message-id="streamingAssistantMessageId"
          @new-chat="createNewChat"
          @resume-latest="refreshChatSessions({ resumeLatest: true })"
        />

        <DocumentPool
          v-else
          v-model:document-search-query="documentSearchQuery"
          v-model:document-type-filter="documentTypeFilter"
          :active-count="activeDocuments.length"
          :deleting-document-ids="deletingDocumentIds"
          :documents="documents"
          :documents-message="documentsMessage"
          :documents-status="documentsStatus"
          :document-pending-delete="documentPendingDelete"
          :filtered-documents="filteredDocuments"
          :indexed-documents="indexedDocuments"
          :queued-documents="queuedDocuments"
          :storage-used="storageUsed"
          :upload-status="uploadStatus"
          @cancel-delete="cancelDeleteDocument"
          @confirm-delete="confirmDeleteDocument"
          @refresh="refreshDocuments"
          @request-delete="requestDeleteDocument"
          @upload="handleUploadDocument"
        />

        <template #composer>
          <ChatComposer
            v-if="activeSection === 'chat'"
            v-model="composerContent"
            :can-send="canSendChatMessage"
            :has-active-session="Boolean(activeChatSession)"
            :streaming="chatStreaming"
            @send="sendChatMessage"
          />
        </template>
      </WorkspaceShell>
    </AccessGate>
  </main>
</template>
