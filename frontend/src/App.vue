<script setup lang="ts">
import {
  SignInButton,
  SignOutButton,
  SignUpButton,
  SignedIn,
  SignedOut,
  UserButton,
  useAuth,
  useUser
} from "@clerk/vue";
import { LogIn, LogOut, RefreshCw, ShieldCheck, UserPlus } from "lucide-vue-next";
import { computed, ref } from "vue";

import { type ApiStatus, fetchCurrentUser } from "./lib/api";

const isClerkConfigured = Boolean(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY);
const auth = isClerkConfigured ? useAuth() : null;
const clerkUser = isClerkConfigured ? useUser() : null;

const apiStatus = ref<ApiStatus>({
  state: "idle",
  message: "Backend identity has not been checked yet."
});

const displayName = computed(() => {
  return (
    clerkUser?.user.value?.fullName ?? clerkUser?.user.value?.primaryEmailAddress?.emailAddress ?? "Signed-in teammate"
  );
});

async function checkBackendIdentity() {
  if (!auth) {
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
    const currentUser = await fetchCurrentUser(() => auth.getToken.value());
    apiStatus.value = {
      state: "ready",
      message: "Backend accepted the Clerk session token.",
      user: currentUser
    };
  } catch (error) {
    apiStatus.value = {
      state: "error",
      message: error instanceof Error ? error.message : "Backend identity check failed."
    };
  }
}
</script>

<template>
  <main class="min-h-screen bg-base-200 text-base-content">
    <section v-if="!isClerkConfigured" class="flex min-h-screen items-center justify-center px-5">
      <div class="w-full max-w-lg rounded-box border border-warning/30 bg-base-100 p-6 shadow-sm">
        <p class="text-sm font-semibold uppercase tracking-[0.16em] text-warning">Configuration needed</p>
        <h1 class="mt-2 text-2xl font-semibold">Missing Clerk publishable key</h1>
        <p class="mt-3 text-sm leading-6 text-base-content/70">
          Set VITE_CLERK_PUBLISHABLE_KEY before starting the frontend to enable sign-in, sign-up, and the protected
          application shell.
        </p>
      </div>
    </section>

    <template v-else>
      <SignedOut>
        <section class="grid min-h-screen grid-cols-1 lg:grid-cols-[1.05fr_0.95fr]">
          <div
            class="flex min-h-[52vh] items-center bg-neutral px-6 py-12 text-neutral-content sm:px-10 lg:min-h-screen lg:px-16"
          >
            <div class="max-w-2xl">
              <p class="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-accent">Internal RAG foundation</p>
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

              <div class="mt-8 flex items-center gap-3 rounded-box bg-base-200 p-4 text-sm text-base-content/70">
                <ShieldCheck class="shrink-0 text-primary" :size="20" />
                <span>Clerk session required</span>
              </div>
            </div>
          </div>
        </section>
      </SignedOut>

      <SignedIn>
        <section class="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-5 py-6 sm:px-8">
          <header class="flex flex-wrap items-center justify-between gap-4 border-b border-base-300 pb-5">
            <div>
              <p class="text-sm font-semibold uppercase tracking-[0.16em] text-primary">RAG service</p>
              <h1 class="mt-1 text-2xl font-semibold sm:text-3xl">Authenticated app shell</h1>
            </div>
            <div class="flex items-center gap-3">
              <UserButton after-sign-out-url="/" />
              <SignOutButton>
                <button class="btn btn-ghost btn-sm">
                  <LogOut :size="16" />
                  Sign out
                </button>
              </SignOutButton>
            </div>
          </header>

          <div class="grid flex-1 gap-6 py-8 lg:grid-cols-[0.9fr_1.1fr]">
            <aside class="rounded-box border border-base-300 bg-base-100 p-6 shadow-sm">
              <p class="text-sm font-medium text-base-content/60">Signed in as</p>
              <h2 class="mt-2 break-words text-2xl font-semibold">{{ displayName }}</h2>

              <div class="mt-6 grid gap-3 text-sm">
                <div class="rounded-box bg-base-200 p-4">
                  <span class="font-medium">Frontend auth</span>
                  <p class="mt-1 text-base-content/65">Clerk session active</p>
                </div>
                <div class="rounded-box bg-base-200 p-4">
                  <span class="font-medium">Backend contract</span>
                  <p class="mt-1 text-base-content/65">Bearer token protected</p>
                </div>
              </div>
            </aside>

            <section class="rounded-box border border-base-300 bg-base-100 p-6 shadow-sm">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p class="text-sm font-medium text-base-content/60">Protected API</p>
                  <h2 class="mt-2 text-2xl font-semibold">Backend identity</h2>
                </div>
                <button
                  class="btn btn-primary"
                  :class="{ 'btn-disabled': apiStatus.state === 'loading' }"
                  :disabled="apiStatus.state === 'loading'"
                  @click="checkBackendIdentity"
                >
                  <span v-if="apiStatus.state === 'loading'" class="loading loading-spinner loading-sm"></span>
                  <RefreshCw v-else :size="18" />
                  Check /api/me
                </button>
              </div>

              <div
                class="mt-6 rounded-box border p-5"
                :class="{
                  'border-base-300 bg-base-200': apiStatus.state === 'idle',
                  'border-info/30 bg-info/10': apiStatus.state === 'loading',
                  'border-success/30 bg-success/10': apiStatus.state === 'ready',
                  'border-error/30 bg-error/10': apiStatus.state === 'error'
                }"
              >
                <p class="font-medium">
                  <span v-if="apiStatus.state === 'ready'">Connected</span>
                  <span v-else-if="apiStatus.state === 'error'">Needs attention</span>
                  <span v-else-if="apiStatus.state === 'loading'">Checking</span>
                  <span v-else>Ready to check</span>
                </p>
                <p class="mt-2 text-sm leading-6 text-base-content/70">{{ apiStatus.message }}</p>

                <dl v-if="apiStatus.user" class="mt-5 grid gap-3 text-sm sm:grid-cols-2">
                  <div class="rounded-box bg-base-100 p-4">
                    <dt class="font-medium text-base-content/60">User ID</dt>
                    <dd class="mt-1 break-all font-mono">{{ apiStatus.user.user_id }}</dd>
                  </div>
                  <div class="rounded-box bg-base-100 p-4">
                    <dt class="font-medium text-base-content/60">Session ID</dt>
                    <dd class="mt-1 break-all font-mono">{{ apiStatus.user.session_id ?? "Not returned" }}</dd>
                  </div>
                  <div class="rounded-box bg-base-100 p-4 sm:col-span-2">
                    <dt class="font-medium text-base-content/60">Email</dt>
                    <dd class="mt-1 break-all font-mono">{{ apiStatus.user.email ?? "Not returned" }}</dd>
                  </div>
                </dl>
              </div>
            </section>
          </div>
        </section>
      </SignedIn>
    </template>
  </main>
</template>
