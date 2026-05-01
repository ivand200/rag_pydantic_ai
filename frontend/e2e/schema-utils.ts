import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = dirname(fileURLToPath(import.meta.url));

export type JsonSchema = {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  additionalProperties?: boolean;
};

export function schemaFromValue(value: unknown): JsonSchema {
  if (value === null) {
    return { type: "null" };
  }

  if (Array.isArray(value)) {
    return {
      type: "array",
      items: value.length > 0 ? schemaFromValue(value[0]) : {}
    };
  }

  if (typeof value === "object") {
    const properties: Record<string, JsonSchema> = {};
    const required: string[] = [];

    for (const [key, child] of Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a.localeCompare(b)
    )) {
      properties[key] = schemaFromValue(child);
      required.push(key);
    }

    return {
      type: "object",
      properties,
      required,
      additionalProperties: true
    };
  }

  return { type: typeof value };
}

export function readSchema(relativePath: string): JsonSchema {
  return JSON.parse(readFileSync(resolve(currentDir, relativePath), "utf8")) as JsonSchema;
}

export function writeSchema(relativePath: string, schema: JsonSchema) {
  const path = resolve(currentDir, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(schema, null, 2)}\n`);
}

export function expectValueMatchesSchema(value: unknown, schema: JsonSchema, path = "$") {
  const allowedTypes = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  const actualType = jsonType(value);

  if (allowedTypes.length > 0 && !allowedTypes.includes(actualType)) {
    throw new Error(`${path} expected ${allowedTypes.join("|")} but received ${actualType}`);
  }

  if (actualType === "object") {
    const objectValue = value as Record<string, unknown>;
    for (const key of schema.required ?? []) {
      if (!(key in objectValue)) {
        throw new Error(`${path}.${key} is missing`);
      }
    }

    for (const [key, childSchema] of Object.entries(schema.properties ?? {})) {
      if (key in objectValue) {
        expectValueMatchesSchema(objectValue[key], childSchema, `${path}.${key}`);
      }
    }
  }

  if (actualType === "array" && schema.items) {
    for (const [index, item] of (value as unknown[]).entries()) {
      expectValueMatchesSchema(item, schema.items, `${path}[${index}]`);
    }
  }
}

export function schemaFileName(name: string) {
  return name.replace(/[^a-z0-9_.-]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

function jsonType(value: unknown) {
  if (value === null) {
    return "null";
  }

  if (Array.isArray(value)) {
    return "array";
  }

  return typeof value;
}
