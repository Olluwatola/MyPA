# MyPA web

Next.js (App Router) client for the MyPA backend. Spec: `dumpbox/PRD-personal-assistant-frontend-mvp.md`;
visual rules: `project-manager/design-system.md` (values live in `src/app/globals.css`).

## Run it

```bash
pnpm install
cp .env.example .env.local   # BACKEND_URL, default http://localhost:8000
pnpm dev                     # http://localhost:3000; /api/* is proxied to BACKEND_URL
```

The backend must be running (`ENVIRONMENT=local`). The browser only talks to this origin, so the
refresh cookie and the Google sign-in flow work without CORS.

## Scripts

| Script | What it does |
|---|---|
| `pnpm gen:api` | Fetch the backend's `/openapi.json` into `openapi.json`, then regenerate `src/lib/api/schema.d.ts`. Commit both |
| `pnpm gen:api:offline` | Regenerate the types from the committed `openapi.json` only |
| `pnpm lint` / `pnpm typecheck` / `pnpm test` / `pnpm build` | Checks; all must be clean before a merge |
| `pnpm analyze` | Turbopack bundle analyzer (first-load size) |

## Auth in one paragraph

The access token lives in memory only (`src/lib/auth/session.ts`), never in web storage. On load,
`AuthProvider` trades the HttpOnly refresh cookie for a token (`/refresh`) before any guarded page
renders. `authFetch` (`src/lib/api/client.ts`) attaches the token, and on a 401 refreshes once and
retries once. Refresh is single-flight because the backend rotates the cookie on every call.
