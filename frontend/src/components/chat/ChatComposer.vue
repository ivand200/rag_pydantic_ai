<script setup lang="ts">
import { Send } from "lucide-vue-next";

defineProps<{
  canSend: boolean;
  hasActiveSession: boolean;
  streaming: boolean;
}>();

const composerContent = defineModel<string>({ required: true });

const emit = defineEmits<{
  send: [];
}>();
</script>

<template>
  <div class="rag-composer">
    <textarea
      v-model="composerContent"
      class="textarea block min-h-24 w-full resize-none rounded-none border-0 bg-white text-lg focus:outline-none disabled:bg-white"
      :disabled="!hasActiveSession || streaming"
      placeholder="Ask about your documents, code, or architecture specs..."
      @keydown.enter.exact.prevent="emit('send')"
    ></textarea>
    <div class="flex items-center justify-between border-t border-[#d1d1d1] px-4 py-3">
      <div class="text-sm text-slate-500">Saved chat session required</div>
      <button
        aria-label="Send"
        class="btn btn-square border-0 bg-[#0082ce] text-white hover:bg-[#00609a]"
        :disabled="!canSend"
        type="button"
        @click="emit('send')"
      >
        <span v-if="streaming" class="loading loading-spinner loading-sm"></span>
        <Send v-else :size="18" />
      </button>
    </div>
    <p class="pb-3 text-center text-xs text-slate-400">
      AI responses may be inaccurate. Verify critical details against original sources.
    </p>
  </div>
</template>
