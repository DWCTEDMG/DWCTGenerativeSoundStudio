import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isPlaceholder } from "./release-candidate-lib.mjs";

export function validateStoreSubmission(document, { production = false } = {}) {
  if (document?.schemaVersion !== 1) throw new Error("Store submission metadata schemaVersion must be 1.");
  const required = ["productId", "identityName", "publisher", "publisherId", "version", "displayName", "publisherDisplayName"];
  for (const key of required) {
    if (isPlaceholder(document[key])) throw new Error(`Store submission ${key} is missing or is a placeholder.`);
  }
  if (!/^CN=/.test(document.publisher)) throw new Error("Store publisher must be the exact Partner Center distinguished name.");
  if (!/^\d{1,5}(?:\.\d{1,5}){2}\.0$/.test(document.version)) throw new Error("Store version must contain four numeric parts and end in .0.");
  for (const part of document.version.split(".")) if (Number(part) > 65535) throw new Error("Store version components must not exceed 65535.");
  for (const key of ["certification", "knownIssues", "rollback"]) {
    if (!document[key] || isPlaceholder(document[key].status) || isPlaceholder(document[key].evidenceReference)) {
      throw new Error(`Store submission ${key} metadata is incomplete or placeholder evidence.`);
    }
  }
  if (production) {
    if (document.certification.status !== "passed") throw new Error("Production Store submission requires externally returned Partner Center certification status 'passed'.");
    if (document.rollback.status !== "validated") throw new Error("Production Store submission requires externally validated rollback metadata.");
  }
  return document;
}

const invoked = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invoked) {
  const input = process.argv[2];
  if (!input) throw new Error("Usage: node validate-store-submission.mjs <metadata.json> [--production]");
  const document = JSON.parse(fs.readFileSync(path.resolve(input), "utf8"));
  validateStoreSubmission(document, { production: process.argv.includes("--production") });
  console.log(JSON.stringify({ ok: true, identityName: document.identityName, version: document.version }, null, 2));
}
