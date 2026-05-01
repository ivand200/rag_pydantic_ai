import { expect, test } from "@playwright/test";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { schemaPaths } from "./schema-paths";

const currentDir = dirname(fileURLToPath(import.meta.url));

test("all e2e schema baselines are checked in", () => {
  for (const [name, schemaPath] of Object.entries(schemaPaths)) {
    expect(existsSync(resolve(currentDir, schemaPath)), `${name} schema exists`).toBe(true);
  }
});
