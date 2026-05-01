import { clerkSetup, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type APIResponse, type Page, type Response, test } from "@playwright/test";

import {
  expectValueMatchesSchema,
  readSchema,
  schemaFileName,
  schemaFromValue,
  writeSchema
} from "./schema-utils";

const publicSchemas = {
  environment: "./schemas/clerk.environment.schema.json",
  client: "./schemas/clerk.client.unauthenticated.schema.json",
  backendUnauthorized: "./schemas/backend.me.unauthenticated.schema.json",
  backendAuthenticated: "./schemas/backend.me.authenticated.schema.json"
};

test("captures real public Clerk environment schema", async ({ request }) => {
  test.skip(
    !process.env.VITE_CLERK_PUBLISHABLE_KEY,
    "Set VITE_CLERK_PUBLISHABLE_KEY for real Clerk schema capture."
  );

  const frontendApiHost = clerkFrontendApiHost();

  const environment = await request.get(`https://${frontendApiHost}/v1/environment`);
  await expectJsonOk(environment, "Clerk /v1/environment");
  await assertOrWriteSchema(publicSchemas.environment, await environment.json());
});

test("captures real browser Clerk client schema", async ({ page }) => {
  test.skip(
    !process.env.VITE_CLERK_PUBLISHABLE_KEY,
    "Set VITE_CLERK_PUBLISHABLE_KEY for real Clerk schema capture."
  );
  test.skip(
    !(await ensureClerkTestingBypass()),
    "Set CLERK_TESTING_TOKEN or CLERK_SECRET_KEY to call Clerk from a browser-origin e2e."
  );

  const environmentPromise = page.waitForResponse((response) =>
    response.url().includes("/v1/environment")
  );
  const clientPromise = page.waitForResponse((response) => response.url().includes("/v1/client"));

  await setupClerkTestingToken({ page, options: { frontendApiUrl: clerkFrontendApiHost() } });
  await page.goto("/");

  const environment = await environmentPromise;
  await expectJsonOk(environment, "Browser Clerk /v1/environment");
  await assertOrWriteSchema(publicSchemas.environment, await environment.json());

  const client = await clientPromise;
  await expectJsonOk(client, "Browser Clerk /v1/client");
  await assertOrWriteSchema(publicSchemas.client, await client.json());
});

test("captures unauthenticated backend auth-contract schema", async ({ request }) => {
  const response = await request.get(`${apiBaseUrl()}/api/me`);

  expect(response.status()).toBe(401);
  await assertOrWriteSchema(publicSchemas.backendUnauthorized, await response.json());
});

test("signs in through real Clerk UI and captures authenticated schemas", async ({ page }) => {
  test.skip(
    !process.env.VITE_CLERK_PUBLISHABLE_KEY,
    "Set VITE_CLERK_PUBLISHABLE_KEY for real Clerk e2e."
  );
  test.skip(!process.env.E2E_CLERK_USER_EMAIL, "Set E2E_CLERK_USER_EMAIL for real Clerk e2e.");
  test.skip(!process.env.E2E_CLERK_USER_PASSWORD, "Set E2E_CLERK_USER_PASSWORD for real Clerk e2e.");
  test.skip(
    !(await ensureClerkTestingBypass()),
    "Set CLERK_TESTING_TOKEN or CLERK_SECRET_KEY to call Clerk from a browser-origin e2e."
  );

  const observedSchemas = new Map<string, unknown>();
  page.on("response", async (response) => {
    const url = response.url();
    if (!response.headers()["content-type"]?.includes("application/json")) {
      return;
    }

    if (!url.includes("clerk.accounts.dev") && !url.includes("/api/me")) {
      return;
    }

    try {
      observedSchemas.set(schemaNameFromUrl(url), await response.json());
    } catch {
      // Some Clerk responses are intentionally opaque; ignore non-JSON bodies.
    }
  });

  await setupClerkTestingToken({ page, options: { frontendApiUrl: clerkFrontendApiHost() } });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.locator(".cl-signIn-root").waitFor({ state: "attached" });
  await fillClerkSignInForm(page, process.env.E2E_CLERK_USER_EMAIL!, process.env.E2E_CLERK_USER_PASSWORD!);

  await expect(page.getByRole("heading", { name: "Authenticated app shell" })).toBeVisible({
    timeout: 45_000
  });

  await page.getByRole("button", { name: "Check /api/me" }).click();
  await expect(page.getByText("Backend accepted the Clerk session token.")).toBeVisible({
    timeout: 30_000
  });

  const meResponse = await page.waitForResponse((response) => response.url().includes("/api/me") && response.ok());
  const meBody = await meResponse.json();
  await assertOrWriteSchema(publicSchemas.backendAuthenticated, meBody);

  if (shouldWriteSchemas()) {
    for (const [name, value] of observedSchemas) {
      writeSchema(`./schemas/observed/${name}.schema.json`, schemaFromValue(value));
    }
  }
});

async function fillClerkSignInForm(page: Page, email: string, password: string) {
  const identifierInput = page.locator('input[name="identifier"], input[name="emailAddress"]').first();
  await identifierInput.waitFor({ state: "visible" });
  await identifierInput.fill(email);

  const passwordInput = page.locator('input[name="password"]').first();
  if (await passwordInput.isVisible()) {
    await passwordInput.fill(password);
  }

  await page.getByRole("button", { name: /continue|sign in/i }).first().click();

  if (!(await passwordInput.isVisible())) {
    await passwordInput.waitFor({ state: "visible", timeout: 15_000 });
    await passwordInput.fill(password);
    await page.getByRole("button", { name: /continue|sign in/i }).first().click();
  }
}

async function assertOrWriteSchema(relativePath: string, value: unknown) {
  const schema = schemaFromValue(value);
  if (shouldWriteSchemas()) {
    writeSchema(relativePath, schema);
    return;
  }

  expectValueMatchesSchema(value, readSchema(relativePath));
}

function clerkFrontendApiHost() {
  const key = process.env.VITE_CLERK_PUBLISHABLE_KEY;
  if (!key) {
    throw new Error("VITE_CLERK_PUBLISHABLE_KEY is required for Clerk e2e schema capture.");
  }

  const match = key.match(/^pk_(?:test|live)_(.+)$/);
  if (!match) {
    throw new Error("VITE_CLERK_PUBLISHABLE_KEY format is not recognized.");
  }

  return Buffer.from(match[1], "base64").toString("utf8").replace(/\$$/, "");
}

async function ensureClerkTestingBypass() {
  process.env.CLERK_FAPI ??= clerkFrontendApiHost();

  if (process.env.CLERK_TESTING_TOKEN) {
    return true;
  }

  if (!process.env.CLERK_SECRET_KEY) {
    return false;
  }

  await clerkSetup({
    dotenv: false,
    frontendApiUrl: clerkFrontendApiHost(),
    publishableKey: process.env.VITE_CLERK_PUBLISHABLE_KEY,
    secretKey: process.env.CLERK_SECRET_KEY
  });
  return Boolean(process.env.CLERK_TESTING_TOKEN);
}

function apiBaseUrl() {
  return (process.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

function testBaseUrl() {
  return (process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.E2E_FRONTEND_PORT ?? "5173"}`).replace(
    /\/$/,
    ""
  );
}

function shouldWriteSchemas() {
  return process.env.E2E_WRITE_SCHEMAS === "1";
}

function schemaNameFromUrl(url: string) {
  const parsed = new URL(url);
  return schemaFileName(`${parsed.hostname}${parsed.pathname}`);
}

async function expectJsonOk(response: APIResponse | Response, label: string) {
  if (response.ok()) {
    return;
  }

  throw new Error(`${label} failed with ${response.status()}: ${(await response.text()).slice(0, 500)}`);
}
