<script setup lang="ts">
import { SignOutButton, UserButton } from "@clerk/vue";
import {
  Database,
  FolderOpen,
  LogOut,
  MessageSquare,
  Plus,
  RefreshCw,
  Trash2
} from "lucide-vue-next";

import type { ApiStatus, ChatSessionSummary } from "../lib/api";

type WorkspaceSection = "chat" | "documents";
type ChatStatus = "idle" | "loading" | "ready" | "error";

const props = defineProps<{
  activeSection: WorkspaceSection;
  apiStatus: ApiStatus;
  chatSessions: ChatSessionSummary[];
  chatStatus: ChatStatus;
  creatingChatSession: boolean;
  deletingChatSessionIds: Set<string>;
  isWorkspacePreview: boolean;
  loadingChatSessionId: string | null;
  selectedChatSessionId: string | null;
}>();

const emit = defineEmits<{
  checkBackendIdentity: [];
  deleteChatSession: [sessionId: string];
  loadChatSession: [sessionId: string];
  newChat: [];
  refreshChatSessions: [options: { resumeLatest: boolean }];
  "update:activeSection": [section: WorkspaceSection];
}>();

function sessionPreview(session: ChatSessionSummary) {
  return session.last_message?.content ?? "No messages yet";
}

function sessionTimestamp(session: ChatSessionSummary) {
  return formatDate(session.last_message_at ?? session.updated_at ?? session.created_at);
}

function formatDate(value?: string | null) {
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
</script>

<template>
  <section class="rag-architect min-h-screen" data-theme="ragcorp">
    <aside class="rag-sidebar">
      <div class="border-b border-white/10 p-6">
        <div class="flex items-center gap-3">
          <div class="grid h-9 w-9 place-items-center rounded bg-[#0a2238] text-[#99cbff]">
            <Database :size="20" />
          </div>
          <div>
            <h1 class="text-xl font-bold tracking-tight text-white">RAG Architect</h1>
            <p class="mt-1 text-xs text-slate-400">Enterprise Tier</p>
          </div>
        </div>
        <button
          class="btn mt-8 w-full border-0 bg-[#0082ce] text-white hover:bg-[#00609a]"
          :disabled="creatingChatSession"
          type="button"
          @click="emit('newChat')"
        >
          <span v-if="creatingChatSession" class="loading loading-spinner loading-sm"></span>
          <Plus v-else :size="18" />
          New Chat
        </button>
      </div>

      <nav class="flex-1 py-4">
        <button
          class="rag-nav-item"
          :class="{ 'is-active': activeSection === 'chat' }"
          type="button"
          @click="emit('update:activeSection', 'chat')"
        >
          <MessageSquare :size="21" />
          Chat History
        </button>
        <button
          class="rag-nav-item"
          :class="{ 'is-active': activeSection === 'documents' }"
          type="button"
          @click="emit('update:activeSection', 'documents')"
        >
          <FolderOpen :size="21" />
          Document Pools
        </button>
      </nav>

      <section class="border-t border-white/10 px-5 py-4">
        <div class="mb-3 flex items-center justify-between gap-3">
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Saved Sessions
          </p>
          <button
            class="btn btn-ghost btn-xs text-slate-300"
            :disabled="chatStatus === 'loading'"
            type="button"
            @click="emit('refreshChatSessions', { resumeLatest: false })"
          >
            <span v-if="chatStatus === 'loading'" class="loading loading-spinner loading-xs"></span>
            <RefreshCw v-else :size="14" />
          </button>
        </div>

        <div
          v-if="chatSessions.length === 0"
          class="rounded border border-white/10 bg-white/[0.06] p-3 text-sm text-slate-300"
        >
          No saved chats
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="session in chatSessions"
            :key="session.id"
            class="rounded border p-3 transition"
            :class="
              selectedChatSessionId === session.id
                ? 'border-[#0082ce] bg-white/10 text-white'
                : 'border-white/10 bg-white/[0.04] text-slate-300'
            "
          >
            <div class="flex items-start gap-2">
              <button
                class="min-w-0 flex-1 text-left"
                :disabled="
                  loadingChatSessionId === session.id || deletingChatSessionIds.has(session.id)
                "
                type="button"
                @click="emit('loadChatSession', session.id)"
              >
                <span class="line-clamp-1 text-sm font-semibold">{{ session.title }}</span>
              </button>
              <span
                v-if="loadingChatSessionId === session.id"
                class="loading loading-spinner loading-xs mt-1"
              ></span>
              <button
                class="btn btn-ghost btn-xs btn-square text-slate-400 hover:bg-white/10 hover:text-white"
                :aria-label="`Delete ${session.title}`"
                :disabled="deletingChatSessionIds.has(session.id)"
                type="button"
                @click="emit('deleteChatSession', session.id)"
              >
                <span
                  v-if="deletingChatSessionIds.has(session.id)"
                  class="loading loading-spinner loading-xs"
                ></span>
                <Trash2 v-else :size="14" />
              </button>
            </div>
            <p class="mt-1 line-clamp-2 text-xs text-slate-400">{{ sessionPreview(session) }}</p>
            <p class="mt-2 text-[11px] uppercase tracking-wider text-slate-500">
              {{ sessionTimestamp(session) }}
            </p>
          </div>
        </div>
      </section>

      <section class="border-t border-white/10 px-5 py-4">
        <div class="rounded-lg border border-white/10 bg-white/[0.06] p-4">
          <div class="flex items-center justify-between gap-3">
            <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Backend Identity
            </p>
            <span
              class="h-2.5 w-2.5 rounded-full"
              :class="{
                'bg-slate-500': apiStatus.state === 'idle',
                'bg-[#0082ce]': apiStatus.state === 'loading',
                'bg-[#009689]': apiStatus.state === 'ready',
                'bg-[#ba1a1a]': apiStatus.state === 'error'
              }"
            ></span>
          </div>

          <p class="mt-3 break-words text-sm leading-5 text-slate-300">{{ apiStatus.message }}</p>

          <dl v-if="apiStatus.user" class="mt-4 space-y-3 border-t border-white/10 pt-3 text-xs">
            <div>
              <dt class="font-semibold uppercase tracking-wider text-slate-500">App User ID</dt>
              <dd class="mt-1 break-all font-mono text-slate-300">{{ apiStatus.user.id }}</dd>
            </div>
            <div>
              <dt class="font-semibold uppercase tracking-wider text-slate-500">Email</dt>
              <dd class="mt-1 break-all font-mono text-slate-300">
                {{ apiStatus.user.email ?? "Not returned" }}
              </dd>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <dt class="font-semibold uppercase tracking-wider text-slate-500">First</dt>
                <dd class="mt-1 break-all font-mono text-slate-300">
                  {{ apiStatus.user.first_name ?? "Not returned" }}
                </dd>
              </div>
              <div>
                <dt class="font-semibold uppercase tracking-wider text-slate-500">Last</dt>
                <dd class="mt-1 break-all font-mono text-slate-300">
                  {{ apiStatus.user.last_name ?? "Not returned" }}
                </dd>
              </div>
            </div>
          </dl>
        </div>
      </section>
    </aside>

    <div class="rag-frame">
      <header class="rag-topbar">
        <div class="ml-auto flex items-center gap-3">
          <button
            class="btn btn-sm border-0 bg-[#0082ce] text-white hover:bg-[#00609a]"
            :disabled="apiStatus.state === 'loading'"
            @click="emit('checkBackendIdentity')"
          >
            <span
              v-if="apiStatus.state === 'loading'"
              class="loading loading-spinner loading-xs"
            ></span>
            <RefreshCw v-else :size="16" />
            Check /api/me
          </button>
          <UserButton v-if="!isWorkspacePreview" after-sign-out-url="/" />
          <SignOutButton v-if="!isWorkspacePreview">
            <button class="btn btn-ghost btn-sm text-[#181a2a]">
              <LogOut :size="16" />
              Sign out
            </button>
          </SignOutButton>
          <span
            v-else
            class="rounded border border-[#d1d1d1] bg-white px-2 py-1 text-xs text-[#404751]"
          >
            Preview auth
          </span>
        </div>
      </header>

      <main class="rag-content">
        <slot />
      </main>

      <slot name="composer" />
      <slot name="modal" />
    </div>
  </section>
</template>
