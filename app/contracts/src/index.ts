import { readFileSync } from "node:fs";
import Ajv2020, { type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { parse } from "yaml";

const CONTRACT_ID = "https://contracts.invalid/carrier.openapi.yaml";
const HTTP_METHODS = ["get", "put", "post", "delete", "patch", "head", "options"] as const;

export interface Operation {
  operationId: string;
  /** Path template as written in the contract, for example `/v1/shipments/{id}`. */
  template: string;
  method: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

interface OpenApiDocument {
  paths: Record<string, Record<string, { operationId: string }>>;
}

export interface Contract {
  findOperation(method: string, pathname: string): Operation | undefined;
  validateResponse(method: string, pathname: string, status: number, body: unknown): ValidationResult;
}

function templateMatcher(template: string): RegExp {
  const pattern = template
    .split("/")
    .map((segment) => (/^\{[^}]+\}$/.test(segment) ? "[^/]+" : segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("/");
  return new RegExp(`^${pattern}$`);
}

function pointerEscape(segment: string): string {
  return segment.replace(/~/g, "~0").replace(/\//g, "~1");
}

/** Loads the carrier OpenAPI 3.1 document and validates real HTTP exchanges against it with a JSON Schema 2020-12 validator. */
export function loadCarrierContract(): Contract {
  const document = parse(readFileSync(new URL("../carrier.openapi.yaml", import.meta.url), "utf8")) as OpenApiDocument;

  const ajv = new Ajv2020({ strict: false, allErrors: true });
  addFormats(ajv);
  ajv.addSchema({ ...document, $id: CONTRACT_ID });

  const operations = Object.entries(document.paths).flatMap(([template, item]) =>
    HTTP_METHODS.filter((method) => item[method]).map((method) => ({
      operation: { operationId: item[method]!.operationId, template, method: method.toUpperCase() },
      matches: templateMatcher(template),
    })),
  );

  const validators = new Map<string, ValidateFunction | undefined>();

  function schemaValidator(operation: Operation, status: number): ValidateFunction | undefined {
    const pointer = [
      "paths",
      operation.template,
      operation.method.toLowerCase(),
      "responses",
      String(status),
      "content",
      "application/json",
      "schema",
    ]
      .map(pointerEscape)
      .join("/");
    if (!validators.has(pointer)) validators.set(pointer, ajv.getSchema(`${CONTRACT_ID}#/${pointer}`));
    return validators.get(pointer);
  }

  function findOperation(method: string, pathname: string): Operation | undefined {
    const upper = method.toUpperCase();
    return operations.find((o) => o.operation.method === upper && o.matches.test(pathname))?.operation;
  }

  return {
    findOperation,

    validateResponse(method, pathname, status, body) {
      const operation = findOperation(method, pathname);
      if (!operation) return { valid: false, errors: [`${method.toUpperCase()} ${pathname} is not an operation in the contract`] };

      const validate = schemaValidator(operation, status);
      if (!validate) {
        return { valid: false, errors: [`${operation.operationId} does not document a ${status} response`] };
      }
      const valid = validate(body) as boolean;
      const errors = (validate.errors ?? []).map((e) => `${e.instancePath || "(root)"} ${e.message ?? "is invalid"}`);
      return { valid, errors };
    },
  };
}
