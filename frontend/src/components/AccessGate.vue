<script setup lang="ts">
import { SignInButton, SignUpButton, SignedIn, SignedOut } from "@clerk/vue";
import { LogIn, ShieldCheck, UserPlus } from "lucide-vue-next";

defineProps<{
  canShowWorkspace: boolean;
  isWorkspacePreview: boolean;
}>();
</script>

<template>
  <section v-if="!canShowWorkspace" class="flex min-h-screen items-center justify-center px-5">
    <div class="w-full max-w-lg rounded-box border border-warning/30 bg-base-100 p-6 shadow-sm">
      <p class="text-sm font-semibold uppercase tracking-[0.16em] text-warning">
        Configuration needed
      </p>
      <h1 class="mt-2 text-2xl font-semibold">Missing Clerk publishable key</h1>
      <p class="mt-3 text-sm leading-6 text-base-content/70">
        Set VITE_CLERK_PUBLISHABLE_KEY before starting the frontend to enable sign-in, sign-up, and
        the protected application shell.
      </p>
    </div>
  </section>

  <template v-else>
    <SignedOut v-if="!isWorkspacePreview">
      <section class="grid min-h-screen grid-cols-1 lg:grid-cols-[1.05fr_0.95fr]">
        <div
          class="flex min-h-[52vh] items-center bg-neutral px-6 py-12 text-neutral-content sm:px-10 lg:min-h-screen lg:px-16"
        >
          <div class="max-w-2xl">
            <p class="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-accent">
              Internal RAG foundation
            </p>
            <h1 class="text-4xl font-semibold leading-tight sm:text-5xl">
              Clerk-secured workspace for service teams.
            </h1>
            <p class="mt-5 max-w-xl text-base leading-7 text-neutral-content/75">
              A focused authenticated entry point with a live backend identity check.
            </p>
          </div>
        </div>

        <div class="flex items-center px-6 py-10 sm:px-10 lg:px-16">
          <div class="w-full max-w-md">
            <div class="mb-8">
              <p class="text-sm font-medium text-base-content/60">Access</p>
              <h2 class="mt-2 text-3xl font-semibold">Welcome in</h2>
            </div>

            <div class="flex flex-col gap-3 sm:flex-row">
              <SignInButton mode="modal">
                <button class="btn btn-primary flex-1">
                  <LogIn :size="18" />
                  Sign in
                </button>
              </SignInButton>
              <SignUpButton mode="modal">
                <button class="btn btn-outline flex-1">
                  <UserPlus :size="18" />
                  Create account
                </button>
              </SignUpButton>
            </div>

            <div
              class="mt-8 flex items-center gap-3 rounded-box bg-base-200 p-4 text-sm text-base-content/70"
            >
              <ShieldCheck class="shrink-0 text-primary" :size="20" />
              <span>Clerk session required</span>
            </div>
          </div>
        </div>
      </section>
    </SignedOut>

    <component :is="isWorkspacePreview ? 'div' : SignedIn">
      <slot />
    </component>
  </template>
</template>
