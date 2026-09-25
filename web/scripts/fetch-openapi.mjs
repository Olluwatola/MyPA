// Pulls the backend's OpenAPI schema into web/openapi.json (committed, so the frontend builds
// without a running backend and API changes show up as a diff). The backend only serves it while
// ENVIRONMENT=local.
import { writeFile } from "node:fs/promises";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
const url = `${backendUrl}/openapi.json`;

const response = await fetch(url);
if (!response.ok) {
  console.error(`GET ${url} -> ${response.status}. Is the backend running with ENVIRONMENT=local?`);
  process.exit(1);
}

const schema = await response.json();
await writeFile(new URL("../openapi.json", import.meta.url), `${JSON.stringify(schema, null, 2)}\n`);
console.log(`Wrote openapi.json from ${url}`);
