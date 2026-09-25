# Feature F1.1 — App shell + auth: implementation plan

Status: **ALL CALLS CONFIRMED 2026-09-25** — Tola chose the recommended answer to every question
(Q1 pnpm, Q2 openapi-fetch, Q3 commit both files, Q4 `/signup` page, Q5 call both routes / no
backend change, Q7 Vitest now + Playwright from F1.4, Q8 react-hook-form + zod). Q6 (client-side
guard) wasn't asked — it's the only option that works with an in-memory token. Design calls
confirmed too (teal, serif, classic bubbles). **Built 2026-09-26** ("implement this"); deviations are in
`decisions-log.md` 2026-09-26.
Written: 2026-09-25.
Branch: `feature/F1.1-app-shell-auth`, to be created from `feature/1.9-goal-tracking@e46e9e3`.
Source of truth: `dumpbox/PRD-personal-assistant-frontend-mvp.md` §3, §4, §6, §7, §8.
Visual rules: `project-manager/design-system.md` (tokens, type, motion). F1.1 sets them up;
later features only use them.

---

## 0. What I checked before writing this

**Backend auth, read from the code, not the PRD.**

| Route | Shape | Notes for the frontend |
|---|---|---|
| `POST /api/v1/register` | JSON `UserCreate`: `first_name` (1–30), `last_name?` (1–30), `email`, `password` (≥ 8), `timezone` (default `UTC`), `extra="forbid"` | Returns `UserRead` (201). **Does not log in.** Duplicate email → **422** `{"detail": "Email is already registered"}` (FastCRUD's `DuplicateValueException` is 422, not 409) |
| `POST /api/v1/login` | **form-encoded** `OAuth2PasswordRequestForm`: `username` (= email), `password` | Returns `{access_token, token_type}`. Sets `refresh_token` cookie: `HttpOnly; Secure; SameSite=Lax; Path=/api/v1`, 7 days. Wrong credentials → 401 `"Wrong email or password."` |
| `POST /api/v1/refresh` | no body, cookie only | **Rotates**: blacklists the old refresh token and sets a new one. Replaying the old cookie → 401 |
| `POST /api/v1/logout` | bearer token + cookie | 204, blacklists both, deletes the cookie |
| `GET /api/v1/users/me` | bearer | `UserRead`: `id, first_name, last_name, email, timezone, is_superuser`. **No onboarding status** |
| `GET /api/v1/onboarding/status` | bearer | `{onboarding_status: not_started\|pending\|ready\|completed, onboarding_suggested_goals, onboarding_completed_at}` |
| `GET /api/v1/auth/google/login` | browser navigation, no token | Sets a state cookie, 302 to Google |
| `GET /api/v1/auth/google/callback` | from Google | Sets **only** the refresh cookie, 302 to `FRONTEND_OAUTH_CALLBACK_URL` = `http://localhost:3000/auth/callback`. The frontend must call `/refresh` on landing to get an access token |

Errors are `{"detail": string}`, and 422 validation errors are `{"detail": [{loc, msg, type}]}`.
Access token lives 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`).

**OpenAPI.** The schema is served at `http://localhost:8000/openapi.json` (the root, not under `/api`)
while `ENVIRONMENT=local`. No hand-written API docs exist.

**Tooling on this machine.** Node 24.14, npm 11.9, pnpm 10.32. Latest on npm today: `next` 16.3.6,
`react` 19.3.0, `tailwindcss` 4.3.3, `@tanstack/react-query` 5.103.2, `openapi-typescript` 7.13.0,
`openapi-fetch` 0.17.0, `shadcn` 4.21.0, `vitest` 5.0.2, `@testing-library/react` 16.3.3, `msw`
2.15.0.

**Two things in the backend that shape the design:**
1. **Refresh rotation + React StrictMode.** In dev, StrictMode runs effects twice. Two boot-time
   `/refresh` calls race: the first rotates the cookie, the second sends the now-blacklisted cookie
   and gets 401, which would log the user out on every reload. Refresh **must** be single-flight
   (one shared promise). Same fix covers several queries getting 401 at the same moment.
2. **Cookies ignore ports.** The refresh cookie is set for host `localhost` with `Path=/api/v1`, so
   it's sent to `localhost:3000/api/v1/*` (through the dev proxy) as well as `localhost:8000`. The
   Google state cookie set via the proxy is therefore still present when Google redirects to the
   backend callback on `:8000`. The proxy (N-35) works for every auth flow.

---

## 1. Open questions (recommendation first)

### Q1. Package manager → **pnpm**
Installed, fast, strict about undeclared deps. `web/` is a standalone package (no workspace — the
backend is Python/uv).

### Q2. API client → **`openapi-fetch` + types from `openapi-typescript`**
`openapi-fetch` is a ~6 kB typed `fetch` wrapper: paths, params, bodies and responses all type-check
against the generated schema. Alternatives: hand-written `fetch` (types drift) or a full codegen
client like orval (more generated code, more to maintain). We give `openapi-fetch` our own `fetch`
function for the token/refresh logic (§5.2).

### Q3. How the schema gets into the repo → **commit both `web/openapi.json` and the generated `web/src/lib/api/schema.d.ts`**
- `pnpm gen:api` = fetch `http://localhost:8000/openapi.json` → `web/openapi.json`, then
  `openapi-typescript openapi.json -o src/lib/api/schema.d.ts`.
- `pnpm gen:api:offline` = the second step only.
Committing both means the frontend builds without a running backend, and every backend API change
shows up as a readable diff in the PR. Backend URL from `BACKEND_URL` (default
`http://localhost:8000`).

### Q4. Signup screen → **add `/signup`**
The PRD's route list only has `/login`, but §6 says "login/signup screens". A separate route is
simpler than a toggle and linkable. Small deviation; logged if accepted.

### Q5. Where the onboarding gate reads from → **`GET /onboarding/status` at boot, no backend change**
`UserRead` has no onboarding status. Boot fires `/users/me` and `/onboarding/status` in parallel
after refresh. Alternative: add `onboarding_status` to `UserRead` (one fewer call, but a backend
change in a frontend feature). Not worth it now.

### Q6. Route protection → **client-side guard in the `(app)` layout, no Next middleware**
Middleware runs on the server and can't see the token (memory only) or the refresh cookie (its
`Path=/api/v1` means it isn't sent for `/chat`). A client guard with a loading skeleton is the only
option that works, and it's what PRD §6 describes ("silent refresh on initial load before rendering
any authenticated route").

### Q7. Tests → **Vitest + Testing Library + MSW now; Playwright later**
Unit/integration tests cover the risky logic (refresh, guard). A browser E2E suite pays off once
there are real flows to click through (F1.4 onward). The live walkthrough (§9) covers F1.1's
end-to-end.

### Q8. Forms → **react-hook-form + zod through shadcn's `Form`**
Client rules mirror the backend (`first_name` 1–30, password ≥ 8, email) for instant feedback; the
server's `detail` is still shown when it disagrees.

---

## 2. Build order

0. Backend fix B-06 (`ClientCacheMiddleware`: `private, no-cache` for `/api/`) + its test.
1. Branch, scaffold `web/` (create-next-app: TypeScript, App Router, `src/`, Tailwind, ESLint).
2. Design tokens, fonts and base styles from `design-system.md` into `globals.css`; `shadcn init`
   and the components listed in §4.
3. `next.config.ts` rewrites (dev proxy), `.env.example`, `gen:api` scripts, commit the first
   `openapi.json` + `schema.d.ts`.
4. Session store, single-flight refresh, API client (§5).
5. `AuthProvider`, `QueryProvider`, `Toaster` in the root layout.
6. Routes: `/login`, `/signup`, `/auth/callback`, `/`, `(app)` guard + shell, placeholder pages.
7. Tab bar (§7).
8. Tests (§8), then lint / typecheck / test / build.
9. Live walkthrough against the real backend (§9).
10. Office updates (§10).

---

## 3. Scaffold and config

```
web/
├── openapi.json                  # committed snapshot of the backend schema
├── next.config.ts                # rewrites /api/* → BACKEND_URL
├── .env.example                  # BACKEND_URL=http://localhost:8000
├── components.json               # shadcn
├── vitest.config.ts
├── package.json                  # "engines": { "node": ">=24" }, packageManager pnpm
└── src/
    ├── app/
    │   ├── layout.tsx            # fonts, providers, <Toaster/>
    │   ├── globals.css           # tokens (design-system.md)
    │   ├── page.tsx              # / → redirect by session
    │   ├── (auth)/login/page.tsx
    │   ├── (auth)/signup/page.tsx
    │   ├── (auth)/layout.tsx     # centered card, redirects to /chat if signed in
    │   ├── auth/callback/page.tsx
    │   ├── onboarding/page.tsx   # placeholder until F1.4 (guarded, no tab bar)
    │   └── (app)/
    │       ├── layout.tsx        # guard + AppShell (tab bar)
    │       ├── chat/page.tsx     # empty-state placeholder until F1.2
    │       ├── tasks/page.tsx    # until F1.5
    │       ├── goals/page.tsx    # until F1.6
    │       └── settings/page.tsx # until F1.7 — has a working "Log out" button now
    ├── components/
    │   ├── ui/                   # shadcn output
    │   ├── app-shell.tsx
    │   ├── tab-bar.tsx
    │   └── empty-state.tsx
    ├── lib/
    │   ├── api/schema.d.ts       # generated
    │   ├── api/client.ts         # openapi-fetch + authFetch
    │   ├── api/errors.ts         # detail → message
    │   └── auth/                 # session.ts, refresh.ts, auth-provider.tsx, use-session.ts
    └── test/                     # msw handlers, setup
```

`next.config.ts`:
```ts
rewrites: async () => [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL}/api/:path*` }]
```
The browser only ever talks to `localhost:3000`. Production does the same thing in the reverse
proxy (decided 2026-08-28), so the client code is identical in both. SSE through the Next dev
proxy may buffer — irrelevant until the real F1.3 stream exists; noted in §11.

**One backend fix is needed in F1.1 (B-06, found 2026-09-25):** `ClientCacheMiddleware` stamps
`Cache-Control: public, max-age=60` on **every** response, including `/api/v1/users/me` and
`/api/v1/tasks`. The browser would then (a) serve a 60-second-old copy when the app re-fetches after
a change, and (b) could serve user A's `/users/me` to user B after a logout/login on the same
browser. `public` also lets shared caches store personal data (a tenant-isolation risk). Fix:
responses under `/api/` get `Cache-Control: private, no-cache` (store, but always check with the
server first), and the middleware's `public, max-age` stays only for non-API responses. Add a
backend test for both. ETag replies (N-38) later build on `no-cache`: the browser sends
`If-None-Match` by itself and the server can answer `304`.

---

## 4. UI kit

`shadcn init` (Tailwind v4, CSS variables), then: `button`, `input`, `label`, `form`, `card`,
`skeleton`, `sonner`, `separator`. Icons: `lucide-react` (shadcn's default). shadcn's default
colors are replaced by the tokens in `design-system.md`, not layered on top.

---

## 5. Auth core

### 5.1 Session store (`lib/auth/session.ts`)
A module-level variable holding `accessToken: string | null` plus a subscribe function. Module
level (not only React state) because the fetch wrapper runs outside React. Still memory only —
never `localStorage`/`sessionStorage` (PRD §8, decision 2026-08-28).

### 5.2 Single-flight refresh + fetch wrapper
```ts
let inflight: Promise<string | null> | null = null;

export function refreshAccessToken(): Promise<string | null> {
  inflight ??= fetch("/api/v1/refresh", { method: "POST", credentials: "same-origin" })
    .then(async (r) => (r.ok ? ((await r.json()) as Token).access_token : null))
    .catch(() => null)
    .then((token) => { setAccessToken(token); return token; })
    .finally(() => { inflight = null; });
  return inflight;
}
```
`authFetch(request)` (passed to `createClient({ fetch: authFetch })`):
1. Attach `Authorization: Bearer <token>` if we have one.
2. Send. If not 401, return.
3. If 401 **and** the path is not `/login`, `/register`, `/refresh` or `/logout`: await
   `refreshAccessToken()`. Got a token → retry the request **once** with it. No token → clear the
   session, clear the query cache and send the user to `/login?next=<current path>`.
The request is cloned before the first send so its body can be replayed.

### 5.3 `AuthProvider` + `useSession()`
State: `{ status: "loading" } | { status: "anonymous" } | { status: "authenticated", user, onboardingStatus }`.
On mount: `refreshAccessToken()` → if a token, fetch `/users/me` and `/onboarding/status` in
parallel → `authenticated`; else `anonymous`. Exposes `login(email, password)`,
`signup(values)`, `logout()`, and `setOnboardingStatus()` (F1.4 will call it on completion).

- `login` posts **form-encoded** (`username=email`).
- `signup` posts `/register` with `timezone: Intl.DateTimeFormat().resolvedOptions().timeZone`,
  then calls `login` with the same credentials.
- `logout` posts `/logout`, then always (even if it fails) clears the token and the query cache and
  goes to `/login`.

No proactive timer refresh: the 401 → refresh path handles expiry, and a timer adds a second place
that rotates the cookie.

### 5.4 Query client
Default `staleTime: 30_000`, `refetchOnWindowFocus: true`, `retry`: never on 4xx, up to 2 on
network/5xx. Mutations show errors with a toast (PRD §7). One client for the whole session, so tab
switches reuse the cache (PRD §8). React Query Devtools in dev only.

**Per-screen cache times (confirmed 2026-09-25, "instant cached screens").** Cached data always
shows instantly; `staleTime` only decides when a quiet background re-check happens. F1.1 exports
the values from `lib/api/query-config.ts` so each feature uses a named value, not a magic number:

| Data | `staleTime` | Why |
|---|---|---|
| `/users/me`, `/onboarding/status` | 5 min | Rarely changes; updated directly by our own mutations |
| Goals list / detail | 5 min | Changes rarely; the app's own edits update the cache directly |
| Tasks list / detail | 30 s | Background jobs (email, Notion) add tasks |
| Integration status | 60 s | Can break at any time (expired token) |
| Chat history | `Infinity` | Kept fresh by the live stream (F1.3), never re-fetched on a timer |

**Hold actions on short drops (confirmed 2026-09-25).** TanStack Query's default
`networkMode: "online"` already pauses queries and mutations while `navigator.onLine` is false and
resumes them when the browser is back online. F1.1 makes that visible and safe:
- A `useIsOffline()` hook plus a slim "You're offline. Changes will send when you're back."
  banner (same slot as the PRD §7 "Reconnecting…" banner, same 3-second delay).
- Mutations are paused, not failed, while offline. Each feature renders a paused mutation's item
  in a "Waiting to send" state (design-system.md §7.6).
- In memory only: closing the tab drops paused actions. Persisting them is part of offline mode,
  parked (P-11).

**Load heavy parts late (confirmed 2026-09-25).** Convention for every feature: anything large
and not needed on first paint loads through `next/dynamic` with a skeleton fallback.
Known cases: FullCalendar (F1.5, only when the Calendar view opens), React Query Devtools (dev
only), the onboarding Notion/Telegram steps (F1.4). Next.js already splits code per route. F1.1
adds `@next/bundle-analyzer` (`pnpm analyze`) to check the first-load size.

---

## 6. Routes and redirects

| Where | Session | Result |
|---|---|---|
| any guarded page | `loading` | Full-screen shell skeleton (never a login flash, PRD §6) |
| `(app)/*`, `/onboarding` | `anonymous` | `/login?next=<path>` |
| `(app)/*` | authenticated, onboarding ≠ `completed` | `/onboarding` |
| `/onboarding` | authenticated, onboarding = `completed` | `/chat` |
| `/login`, `/signup` | authenticated | `next` if it's a safe internal path, else `/chat` |
| `/` | any | `/chat` or `/login` once status is known |
| `/auth/callback` | — | Runs the boot refresh. Token → `/chat` (the guard then applies onboarding). No token → `/login?error=google` |

`next` is only followed if it starts with a single `/` (no `//`, no scheme) — no open redirect.

**Login page:** email, password, "Sign in", a divider, "Continue with Google" (a plain link to
`/api/v1/auth/google/login`), link to `/signup`. 401 → inline "Wrong email or password." under the
form, not a toast (it's about this form).
**Signup page:** first name, last name (optional), email, password (≥ 8, shown as a hint, not only
as an error), "Create account". 422 duplicate → inline on the email field.

---

## 7. App shell and tab bar

- Four destinations, same at every width (PRD §4): Chat, Tasks, Goals, Settings (lucide
  `MessageCircle`, `CheckSquare`, `Target`, `Settings`).
- **< 768px:** fixed bottom bar, icon + label, 56px tall plus `env(safe-area-inset-bottom)`.
  **≥ 768px:** slim top bar, wordmark left, tabs right.
- Each tab is a Next `<Link>` with `aria-current="page"` when active; the bar is a `<nav
  aria-label="Main">`. Tab switches don't animate (used many times a day — design-system.md §6).
- Page content gets bottom padding equal to the bar on mobile so nothing hides behind it.
- `/onboarding` renders without the shell (PRD §5.2: full-screen).

---

## 8. Tests (Vitest + Testing Library + MSW)

`lib/api/client.test.ts`
- Attaches the bearer token.
- 401 → one refresh → retry succeeds with the new token.
- 401, refresh fails → session cleared, redirected to `/login?next=…`.
- Retried request still 401 → no second refresh (no loop).
- **Three parallel requests all 401 → exactly one `/refresh` call** (the rotation race).
- 401 from `/login` → no refresh attempt.

`lib/auth/auth-provider.test.tsx`
- Boot: refresh OK → `authenticated` with user + onboarding status.
- Boot: refresh 401 → `anonymous`.
- **Boot effect run twice (StrictMode) → one `/refresh` call**.
- `signup` sends the browser timezone, then logs in.
- `logout` clears state even when `/logout` fails.

`app/(app)/layout.test.tsx` — the redirect table in §6 (loading, anonymous, onboarding
incomplete, complete). Also `next` rejects `//evil.com` and `https://…`.

`login/page.test.tsx` — 401 shows the inline error; 422 duplicate on signup shows under email.

`lib/api/offline.test.tsx` — going offline shows the banner after the delay; a mutation fired
while offline is paused (not failed) and runs once `onlineManager` reports online again.

Backend (`backend/tests/test_client_cache_middleware.py`) — `/api/...` responses carry
`private, no-cache`; a non-API response keeps `public, max-age`.

Checks: `pnpm lint`, `pnpm typecheck` (`tsc --noEmit`), `pnpm test`, `pnpm build` — all clean.
Backend: `uv run pytest`, `ruff check`, `mypy src` (no new errors over the D-07 baseline of 13).

---

## 9. Live verification

Backend up: `db`/`redis` containers (ports 5434/6380), `uvicorn` on `:8000`. Frontend `pnpm dev`.

1. `pnpm gen:api` pulls the real schema; `pnpm typecheck` passes against it.
2. Sign up → lands on `/onboarding` (new user is `not_started`). DevTools: `refresh_token` cookie is
   HttpOnly; nothing in localStorage/sessionStorage.
3. Hard reload on `/onboarding` → brief skeleton, stays signed in, no login flash. Network: exactly
   **one** `/refresh` despite StrictMode.
4. Set onboarding to `completed` for the test user in psql (F1.4 doesn't exist yet) → reload →
   `/chat` with the tab bar. Visit Tasks / Goals / Settings.
5. Expiry: restart the backend with `ACCESS_TOKEN_EXPIRE_MINUTES=1`, wait, navigate → one 401,
   one `/refresh`, request retried, no visible glitch.
6. Log out → `/login`; Back button doesn't show app pages; the old cookie replayed with curl → 401.
7. Signed-out visit to `/tasks` → `/login?next=/tasks` → sign in → back on `/tasks`.
8. Wrong password → inline error. Duplicate signup → inline email error.
9. Resize to 360px: bottom tab bar, nothing hidden behind it; keyboard-only: tab through the nav,
   focus ring visible, `aria-current` on the active tab.
10. **Slow and offline networks (a standing check for every feature from now on):** DevTools
    → Network → "Slow 3G": first load shows the skeleton, never a blank screen; login still works;
    no double `/refresh`. Then "Offline": the offline banner appears after ~3s, tab switches still
    show cached pages, a sign-in attempt shows a clear "You're offline" error instead of hanging;
    back online → banner leaves and paused requests complete.
11. **Cache headers (B-06 fix):** `curl -i` any `/api/v1/*` route → `Cache-Control: private,
    no-cache`. Log out as user A, log in as user B in the same browser → `/users/me` shows B.
12. **Skipped, reported as skipped:** Google sign-in — no real Google OAuth client (N-14). The
    `/auth/callback` page is covered by tests only.

---

## 10. Office updates when built

- `phase-tracker.md`: F1.1 status and verification notes.
- `decisions-log.md`: sign-off + each answered question (Q1–Q8) + any build deviations.
- `open-items.md`: close B-05 and N-35 (the proxy is built); add anything found.
- `session-notes.md`: session entry.

---

## 11. Not in F1.1

- Onboarding wizard (F1.4) — only the redirect and a placeholder page.
- Any real content in Chat / Tasks / Goals / Settings (F1.2–F1.7). Settings only has "Log out".
- Integration connect buttons (need N-33's backend fix).
- Password change / account delete (need backend endpoints, N-34).
- Cross-tab sync. Logging out in one tab doesn't sign out the others until their next request; two
  tabs refreshing at the exact same moment can log one of them out (rotation). Rare — logged as an
  open item, not solved here.
- SSE through the Next dev proxy (F1.3 will check buffering when the real stream exists).
- Playwright E2E (from F1.4).
