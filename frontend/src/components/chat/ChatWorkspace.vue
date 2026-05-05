<script setup lang="ts">
import { Bot, MessageSquare, Plus, RefreshCw } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

import type { ChatSessionDetail } from "../../lib/api";
import type { ChatStatus } from "../../composables/useChatSessions";
import ChatTranscript from "./ChatTranscript.vue";

type SourceReadiness = {
  tone: "loading" | "error" | "empty" | "pending" | "ready" | "mixed";
  title: string;
  message: string;
};

const props = defineProps<{
  activeChatSession: ChatSessionDetail | null;
  chatMessage: string;
  chatStatus: ChatStatus;
  creatingChatSession: boolean;
  failedDocuments: number;
  indexedDocuments: number;
  queuedDocuments: number;
  sourceReadiness: SourceReadiness;
  streamingAssistantMessageId: string | null;
}>();

const emit = defineEmits<{
  newChat: [];
  resumeLatest: [];
}>();

const chatTranscriptEnd = ref<HTMLElement | null>(null);

const hasSavedMessages = computed(() => (props.activeChatSession?.messages.length ?? 0) > 0);
const chatScrollKey = computed(() => {
  const messages = props.activeChatSession?.messages ?? [];
  const latestMessage = messages[messages.length - 1];
  return [
    props.activeChatSession?.id ?? "",
    messages.length,
    latestMessage?.id ?? "",
    latestMessage?.status ?? "",
    latestMessage?.content.length ?? 0
  ].join(":");
});

watch(
  chatScrollKey,
  () => {
    if (!props.activeChatSession) {
      return;
    }

    scrollChatToLatest();
  },
  { flush: "post" }
);

function scrollChatToLatest(behavior: ScrollBehavior = "auto") {
  void nextTick(() => {
    chatTranscriptEnd.value?.scrollIntoView({ behavior, block: "end" });
    window.requestAnimationFrame(() => {
      window.scrollTo({
        top: document.documentElement.scrollHeight + window.innerHeight,
        behavior
      });
    });
  });
}
</script>

<template>
  <section class="rag-chat-section mx-auto flex w-full max-w-5xl flex-col gap-6">
    <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <p class="text-sm font-semibold uppercase tracking-wider text-[#0082ce]">
          Saved chat history
        </p>
        <h1 class="mt-2 text-4xl font-bold tracking-tight text-[#181a2a]">
          {{ activeChatSession?.title ?? "Chat History" }}
        </h1>
        <p class="mt-2 text-lg text-[#404751]">
          Stream saved-session answers and review citations when indexed sources are available.
        </p>
      </div>
      <button
        class="btn border-0 bg-[#0082ce] text-white hover:bg-[#00609a]"
        :disabled="creatingChatSession"
        type="button"
        @click="emit('newChat')"
      >
        <span v-if="creatingChatSession" class="loading loading-spinner loading-sm"></span>
        <Plus v-else :size="18" />
        New Chat
      </button>
    </div>

    <div
      class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#d1d1d1] bg-white p-3"
    >
      <div class="flex items-center gap-3 text-sm text-[#404751]">
        <span
          class="h-2.5 w-2.5 rounded-full"
          :class="{
            'bg-slate-500': chatStatus === 'idle',
            'bg-[#0082ce]': chatStatus === 'loading',
            'bg-[#009689]': chatStatus === 'ready',
            'bg-[#ba1a1a]': chatStatus === 'error'
          }"
        ></span>
        <span>{{ chatMessage }}</span>
      </div>
      <button
        class="btn btn-ghost btn-sm"
        :disabled="chatStatus === 'loading'"
        type="button"
        @click="emit('resumeLatest')"
      >
        <span v-if="chatStatus === 'loading'" class="loading loading-spinner loading-xs"></span>
        <RefreshCw v-else :size="16" />
        Resume latest
      </button>
    </div>

    <div class="rounded-lg border border-[#d1d1d1] bg-white p-4">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div class="flex items-start gap-3">
          <span
            class="mt-1 h-2.5 w-2.5 rounded-full"
            :class="{
              'bg-[#0082ce]': sourceReadiness.tone === 'loading',
              'bg-[#ba1a1a]': sourceReadiness.tone === 'error',
              'bg-slate-500': sourceReadiness.tone === 'empty',
              'bg-[#b15f00]': sourceReadiness.tone === 'pending',
              'bg-[#009689]': sourceReadiness.tone === 'ready',
              'bg-[#00609a]': sourceReadiness.tone === 'mixed'
            }"
          ></span>
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-[#404751]">
              Source readiness
            </p>
            <h2 class="mt-1 text-base font-semibold text-[#181a2a]">{{ sourceReadiness.title }}</h2>
            <p class="mt-1 text-sm leading-6 text-[#404751]">{{ sourceReadiness.message }}</p>
          </div>
        </div>
        <div class="grid grid-cols-3 gap-2 text-center text-xs text-[#404751]">
          <div class="rounded border border-[#d1d1d1] px-3 py-2">
            <p class="font-mono text-base text-[#181a2a]">{{ indexedDocuments }}</p>
            <p>Indexed</p>
          </div>
          <div class="rounded border border-[#d1d1d1] px-3 py-2">
            <p class="font-mono text-base text-[#181a2a]">{{ queuedDocuments }}</p>
            <p>Pending</p>
          </div>
          <div class="rounded border border-[#d1d1d1] px-3 py-2">
            <p class="font-mono text-base text-[#181a2a]">{{ failedDocuments }}</p>
            <p>Failed</p>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="chatStatus === 'loading' && !activeChatSession"
      class="rounded-lg border border-[#d1d1d1] bg-white p-10 text-center text-[#404751]"
    >
      <span class="loading loading-spinner loading-sm mr-2"></span>
      Loading chat sessions
    </div>

    <div
      v-else-if="!activeChatSession"
      class="rounded-lg border border-[#d1d1d1] bg-white p-10 text-center"
    >
      <div class="mx-auto grid h-12 w-12 place-items-center rounded bg-blue-50 text-[#0082ce]">
        <MessageSquare :size="24" />
      </div>
      <h2 class="mt-4 text-xl font-semibold text-[#181a2a]">No session selected</h2>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-[#404751]">
        Create a new saved session or choose one from the sidebar to review persisted messages.
      </p>
    </div>

    <div
      v-else-if="!hasSavedMessages"
      class="rounded-lg border border-[#d1d1d1] bg-white p-10 text-center"
    >
      <div class="mx-auto grid h-12 w-12 place-items-center rounded bg-[#e8f7f5] text-[#009689]">
        <Bot :size="24" />
      </div>
      <h2 class="mt-4 text-xl font-semibold text-[#181a2a]">New chat is saved</h2>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-[#404751]">
        This session exists in the backend. Ask a question from the composer to stream an answer.
      </p>
      <p class="mt-4 break-all font-mono text-xs text-[#404751]">
        session_id: {{ activeChatSession.id }}
      </p>
    </div>

    <ChatTranscript
      v-else
      :messages="activeChatSession.messages"
      :streaming-assistant-message-id="streamingAssistantMessageId"
    />

    <div ref="chatTranscriptEnd" class="h-1" aria-hidden="true"></div>
  </section>
</template>
