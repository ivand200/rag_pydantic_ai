import { defineConfig, devices } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = dirname(fileURLToPath(import.meta.url));

loadDotenv(resolve(currentDir, "..", ".env"));

const frontendPort = process.env.E2E_FRONTEND_PORT ?? "5173";
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: {
    timeout: 15_000
  },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
    env: {
      VITE_API_BASE_URL: process.env.VITE_API_BASE_URL ?? "http://localhost:8000",
      VITE_CLERK_PUBLISHABLE_KEY: process.env.VITE_CLERK_PUBLISHABLE_KEY ?? ""
    },
    reuseExistingServer: true,
    timeout: 120_000,
    url: baseURL
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});

function loadDotenv(path: string) {
  if (!existsSync(path)) {
    return;
  }

  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      continue;
    }

    const index = trimmed.indexOf("=");
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim();
    process.env[key] ??= value;
  }
}
