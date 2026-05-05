import { computed, onBeforeUnmount, ref, watch } from "vue";

import {
  type ChatMessageRecord,
  type ChatSessionDetail,
  type ChatSessionSummary,
  type ChatStreamFinalEvent,
  type ClerkTokenProvider,
  createChatSession,
  deleteChatSession,
  fetchChatSession,
  fetchChatSessions,
  streamChatMessage
} from "../lib/api";

export type ChatStatus = "idle" | "loading" | "ready" | "error";

export function useChatSessions(options: {
  activateChat: () => void;
  getBackendToken: ClerkTokenProvider | null;
  isSignedInForWorkspace: () => boolean;
}) {
  const chatSessions = ref<ChatSessionSummary[]>([]);
  const activeChatSession = ref<ChatSessionDetail | null>(null);
  const chatStatus = ref<ChatStatus>("idle");
  const chatMessage = ref("Loading saved chat sessions...");
  const creatingChatSession = ref(false);
  const loadingChatSessionId = ref<string | null>(null);
  const deletingChatSessionIds = ref(new Set<string>());
  const didAutoLoadChat = ref(false);
  const composerContent = ref("");
  const activeStreamAbort = ref<AbortController | null>(null);
  const activeStreamRunId = ref<string | null>(null);
  const streamingAssistantMessageId = ref<string | null>(null);
  const chatStreaming = ref(false);

  const selectedChatSessionId = computed(() => activeChatSession.value?.id ?? null);
  const trimmedComposerContent = computed(() => composerContent.value.trim());
  const canSendChatMessage = computed(
    () =>
      Boolean(options.getBackendToken) &&
      Boolean(activeChatSession.value) &&
      trimmedComposerContent.value.length > 0 &&
      !chatStreaming.value &&
      chatStatus.value !== "loading"
  );

  async function refreshChatSessions(
    refreshOptions: { resumeLatest: boolean } = { resumeLatest: false }
  ) {
    if (!options.getBackendToken) {
      chatStatus.value = "error";
      chatMessage.value = "Sign in is required before loading chat sessions.";
      return;
    }

    chatStatus.value = "loading";
    chatMessage.value = "Loading saved chat sessions...";

    try {
      const sessions = await fetchChatSessions(options.getBackendToken);
      chatSessions.value = sessions;

      if (refreshOptions.resumeLatest && sessions.length > 0) {
        await loadChatSession(sessions[0].id);
        chatMessage.value = "Most recent chat session resumed.";
        return;
      }

      if (sessions.length === 0) {
        activeChatSession.value = null;
        chatMessage.value = "No saved chat sessions yet. Start with New Chat.";
      } else {
        chatMessage.value = "Saved chat sessions loaded.";
      }

      chatStatus.value = "ready";
    } catch (error) {
      chatStatus.value = "error";
      chatMessage.value =
        error instanceof Error ? error.message : "Chat session list request failed.";
    }
  }

  async function loadChatSession(sessionId: string) {
    if (!options.getBackendToken) {
      chatStatus.value = "error";
      chatMessage.value = "Sign in is required before loading chat history.";
      return;
    }

    cancelActiveStream();
    loadingChatSessionId.value = sessionId;
    chatStatus.value = "loading";
    chatMessage.value = "Loading chat history...";

    try {
      activeChatSession.value = await fetchChatSession(options.getBackendToken, sessionId);
      upsertSessionSummary(sessionFromDetail(activeChatSession.value));
      chatStatus.value = "ready";
      chatMessage.value =
        activeChatSession.value.messages.length > 0
          ? "Saved message history loaded."
          : "This saved chat has no messages yet.";
      options.activateChat();
    } catch (error) {
      chatStatus.value = "error";
      chatMessage.value = error instanceof Error ? error.message : "Chat history request failed.";
    } finally {
      loadingChatSessionId.value = null;
    }
  }

  async function deleteChatSessionById(sessionId: string) {
    if (!options.getBackendToken || deletingChatSessionIds.value.has(sessionId)) {
      return;
    }

    const nextDeletingIds = new Set(deletingChatSessionIds.value);
    nextDeletingIds.add(sessionId);
    deletingChatSessionIds.value = nextDeletingIds;
    chatMessage.value = "Deleting saved chat session...";
    const isActiveSession = activeChatSession.value?.id === sessionId;

    if (isActiveSession) {
      cancelActiveStream();
    }

    try {
      await deleteChatSession(options.getBackendToken, sessionId);
      chatSessions.value = chatSessions.value.filter((session) => session.id !== sessionId);

      if (isActiveSession) {
        activeChatSession.value = null;
        composerContent.value = "";
        chatMessage.value =
          "Deleted active chat session. Create or select a saved chat to continue.";
      } else {
        chatMessage.value = "Saved chat session deleted.";
      }

      chatStatus.value = "ready";
    } catch (error) {
      chatStatus.value = "error";
      chatMessage.value =
        error instanceof Error ? error.message : "Chat session delete request failed.";
    } finally {
      const remainingDeletingIds = new Set(deletingChatSessionIds.value);
      remainingDeletingIds.delete(sessionId);
      deletingChatSessionIds.value = remainingDeletingIds;
    }
  }

  async function createNewChat() {
    if (!options.getBackendToken) {
      chatStatus.value = "error";
      chatMessage.value = "Sign in is required before creating a chat.";
      return;
    }

    cancelActiveStream();
    creatingChatSession.value = true;
    chatStatus.value = "loading";
    chatMessage.value = "Creating a saved chat session...";

    try {
      const session = await createChatSession(options.getBackendToken);
      activeChatSession.value = session;
      composerContent.value = "";
      upsertSessionSummary(sessionFromDetail(session));
      chatStatus.value = "ready";
      chatMessage.value =
        "New chat session created. Ask a question against the shared document pool.";
      options.activateChat();
    } catch (error) {
      chatStatus.value = "error";
      chatMessage.value = error instanceof Error ? error.message : "New chat request failed.";
    } finally {
      creatingChatSession.value = false;
    }
  }

  async function sendChatMessage() {
    if (!options.getBackendToken || !activeChatSession.value || !canSendChatMessage.value) {
      return;
    }

    cancelActiveStream();
    const sessionId = activeChatSession.value.id;
    const content = trimmedComposerContent.value;
    const runId = crypto.randomUUID();
    const assistantId = `streaming-assistant-${runId}`;
    const now = new Date().toISOString();
    const controller = new AbortController();

    composerContent.value = "";
    activeStreamAbort.value = controller;
    activeStreamRunId.value = runId;
    streamingAssistantMessageId.value = assistantId;
    chatStreaming.value = true;
    chatStatus.value = "ready";
    chatMessage.value = "Streaming answer from the backend...";

    appendLocalMessage({
      id: `streaming-user-${runId}`,
      role: "user",
      content,
      status: "completed",
      created_at: now,
      model: null,
      retrieval_query: null,
      usage: null,
      sources: []
    });
    appendLocalMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      status: "streaming",
      created_at: now,
      model: null,
      retrieval_query: null,
      usage: null,
      sources: []
    });

    try {
      await streamChatMessage(
        options.getBackendToken,
        sessionId,
        content,
        {
          onDelta: (event) => {
            if (activeStreamRunId.value !== runId) {
              return;
            }
            updateLocalMessage(assistantId, (message) => ({
              ...message,
              content: `${message.content}${event.text}`
            }));
          },
          onFinal: (event) => {
            if (activeStreamRunId.value !== runId) {
              return;
            }
            applyStreamFinal(assistantId, event);
            chatMessage.value =
              event.sources.length > 0
                ? "Answer completed with source citations."
                : "Answer completed with no matching source citations.";
          },
          onError: (event) => {
            if (activeStreamRunId.value !== runId) {
              return;
            }
            removeLocalMessage(assistantId);
            chatStatus.value = "error";
            chatMessage.value = event.message;
          }
        },
        { signal: controller.signal }
      );

      if (activeStreamRunId.value === runId && !controller.signal.aborted) {
        await reconcileChatSession(sessionId);
      }
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        return;
      }

      removeLocalMessage(assistantId);
      chatStatus.value = "error";
      chatMessage.value = error instanceof Error ? error.message : "Chat stream failed.";
    } finally {
      if (activeStreamRunId.value === runId) {
        activeStreamAbort.value = null;
        activeStreamRunId.value = null;
        streamingAssistantMessageId.value = null;
        chatStreaming.value = false;
      }
    }
  }

  function resetChatSessions() {
    cancelActiveStream();
    didAutoLoadChat.value = false;
    chatSessions.value = [];
    activeChatSession.value = null;
    deletingChatSessionIds.value = new Set();
    chatStatus.value = "idle";
    chatMessage.value = "Loading saved chat sessions...";
    composerContent.value = "";
  }

  watch(
    () => options.isSignedInForWorkspace(),
    (isSignedIn) => {
      if (isSignedIn && !didAutoLoadChat.value) {
        didAutoLoadChat.value = true;
        void refreshChatSessions({ resumeLatest: true });
      }

      if (!isSignedIn) {
        resetChatSessions();
      }
    },
    { immediate: true }
  );

  onBeforeUnmount(() => {
    cancelActiveStream();
  });

  function sessionFromDetail(session: ChatSessionDetail): ChatSessionSummary {
    const lastMessage =
      session.messages.length > 0 ? session.messages[session.messages.length - 1] : null;

    return {
      id: session.id,
      title: session.title,
      title_status: session.title_status,
      created_at: session.created_at,
      updated_at: session.updated_at,
      last_message_at: session.last_message_at,
      last_message: lastMessage
    };
  }

  function upsertSessionSummary(session: ChatSessionSummary) {
    chatSessions.value = [
      session,
      ...chatSessions.value.filter((current) => current.id !== session.id)
    ].sort((left, right) => {
      const leftTime = Date.parse(left.last_message_at ?? left.updated_at ?? left.created_at);
      const rightTime = Date.parse(right.last_message_at ?? right.updated_at ?? right.created_at);
      return rightTime - leftTime;
    });
  }

  function appendLocalMessage(message: ChatMessageRecord) {
    if (!activeChatSession.value) {
      return;
    }

    activeChatSession.value = {
      ...activeChatSession.value,
      messages: [...activeChatSession.value.messages, message]
    };
  }

  function updateLocalMessage(
    messageId: string,
    update: (message: ChatMessageRecord) => ChatMessageRecord
  ) {
    if (!activeChatSession.value) {
      return;
    }

    activeChatSession.value = {
      ...activeChatSession.value,
      messages: activeChatSession.value.messages.map((message) =>
        message.id === messageId ? update(message) : message
      )
    };
  }

  function removeLocalMessage(messageId: string) {
    if (!activeChatSession.value) {
      return;
    }

    activeChatSession.value = {
      ...activeChatSession.value,
      messages: activeChatSession.value.messages.filter((message) => message.id !== messageId)
    };
  }

  function applyStreamFinal(messageId: string, event: ChatStreamFinalEvent) {
    updateLocalMessage(messageId, (message) => ({
      ...message,
      id: event.assistant_message_id,
      status: "completed",
      model: event.model ?? null,
      usage: event.usage ?? null,
      sources: event.sources
    }));
    streamingAssistantMessageId.value = null;
  }

  async function reconcileChatSession(sessionId: string) {
    if (!options.getBackendToken) {
      return;
    }

    const session = await fetchChatSession(options.getBackendToken, sessionId);
    activeChatSession.value = session;
    upsertSessionSummary(sessionFromDetail(session));
  }

  function cancelActiveStream() {
    activeStreamAbort.value?.abort();
    activeStreamAbort.value = null;
    activeStreamRunId.value = null;
    streamingAssistantMessageId.value = null;
    chatStreaming.value = false;
  }

  function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError";
  }

  return {
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
    resetChatSessions,
    selectedChatSessionId,
    sendChatMessage,
    streamingAssistantMessageId
  };
}
