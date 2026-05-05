<script setup lang="ts">
import type { ChatMessageRecord } from "../../lib/api";
import { formatDate } from "../../composables/useDocuments";

defineProps<{
  messages: ChatMessageRecord[];
  streamingAssistantMessageId: string | null;
}>();

function messageAuthorLabel(message: ChatMessageRecord) {
  return message.role === "assistant" ? "Assistant" : "You";
}

function messageBubbleClass(message: ChatMessageRecord) {
  return message.role === "assistant"
    ? "border-l-[#0082ce] bg-white"
    : "ml-auto border-l-[#009689] bg-[#f7fbfa]";
}

function sourceCardTitle(source: ChatMessageRecord["sources"][number]) {
  const location = [
    source.document_name,
    source.section_title,
    source.page_number ? `page ${source.page_number}` : null
  ]
    .filter(Boolean)
    .join(" / ");

  return location ? `Source ${source.rank} / ${location}` : `Source ${source.rank}`;
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <article
      v-for="message in messages"
      :key="message.id"
      class="max-w-[880px] rounded-lg border border-[#d1d1d1] border-l-4 p-5"
      :class="messageBubbleClass(message)"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-2">
          <span
            class="badge rounded bg-[#009689] px-2 py-3 text-[10px] font-bold uppercase tracking-wider text-white"
          >
            {{ messageAuthorLabel(message) }}
          </span>
          <span class="text-sm text-[#404751]">{{ formatDate(message.created_at) }}</span>
        </div>
        <span class="font-mono text-xs text-[#404751]">{{ message.status }}</span>
      </div>
      <p class="mt-4 whitespace-pre-wrap text-[15px] leading-7 text-[#181a2a]">
        {{ message.content || (message.id === streamingAssistantMessageId ? "Streaming..." : "") }}
      </p>

      <div v-if="message.sources.length > 0" class="mt-5 border-t border-[#d1d1d1] pt-4">
        <h3 class="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Citations
        </h3>
        <div class="grid gap-3">
          <div
            v-for="source in message.sources"
            :key="source.id"
            class="rounded border border-[#d1d1d1] bg-white p-3 text-sm text-[#404751]"
          >
            <div class="mb-2 flex items-center gap-2">
              <span
                class="grid h-6 w-6 place-items-center rounded bg-[#009689] text-xs font-bold text-white"
              >
                {{ source.rank }}
              </span>
              <span class="font-semibold text-[#181a2a]">{{ sourceCardTitle(source) }}</span>
              <span class="font-mono text-xs">score {{ source.score.toFixed(3) }}</span>
            </div>
            <p class="rounded border border-[#d1d1d1] bg-[#f7f8fa] p-3 font-mono text-xs leading-6">
              {{ source.excerpt }}
            </p>
            <p class="mt-2 break-all font-mono text-[11px] text-[#404751]">
              document: {{ source.document_name }}
            </p>
          </div>
        </div>
      </div>
      <div
        v-else-if="message.role === 'assistant' && message.status === 'completed'"
        class="mt-5 rounded border border-[#d1d1d1] bg-[#f7f8fa] p-3 text-sm text-[#404751]"
      >
        No source citations were returned for this answer.
      </div>
    </article>
  </div>
</template>
