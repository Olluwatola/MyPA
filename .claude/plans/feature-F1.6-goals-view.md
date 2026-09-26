# Feature F1.6 — Goals view: implementation plan

Status: **PROPOSED 2026-09-26** — every question in §1 was answered by Tola in two question rounds
(all as recommended). The smaller calls in §1.8 were made by me and are easy to flip. **Built
2026-09-26** ("implement 1.6"); deviations and fixes are in `decisions-log.md` 2026-09-26.
Written: 2026-09-26.
Branch: `feature/F1.6-goals-view` (already created) from `feature/F1.1-app-shell-auth@00d3ef5`.
Source of truth: `dumpbox/PRD-personal-assistant-frontend-mvp.md` §5.4, §7, §8; backend goal rules
from Feature 1.9 (`.claude/plans/feature-1.9-goal-tracking.md`).
Visual rules: `project-manager/design-system.md` §3.3 (badges), §6.2 (motion), §7.3 (lists), §7.4
(forms), §7.6 (states).

---

## 0. What I checked before writing this

**Git.** F1.1 committed as `00d3ef5` on `feature/F1.1-app-shell-auth` (on top of 1.9's `e46e9e3`).
`feature/F1.6-goals-view` created from it; working tree clean apart from gitignored office files.

**Backend goal API (`backend/src/app/api/v1/goals.py`, built in 1.9) — no new routes needed.**

| Route | Notes for the frontend |
|---|---|
| `POST /goals` | Body `GoalCreate`: `title` (1–255), `description?`, `horizon?` (`short_term`/`long_term`), `target_date?` (ISO date). `extra="forbid"`. `source` is forced to `manual`. **`horizon: null` enqueues `guess_goal_horizon`** (AI guess in the background; never overwrites a value set meanwhile) |
| `GET /goals` | Paginated (`page`, `items_per_page` ≤ 100), **newest first**. Filters: `status` (repeatable: `?status=open&status=paused`), `horizon`, `source`. Deleted goals hidden. Response `{data, total_count, has_more, page, items_per_page}` |
| `GET /goals/{id}` | 404 if deleted, 403 if someone else's |
| `PATCH /goals/{id}` | Only sent fields change (`exclude_unset`). `null` clears `description`/`horizon`/`target_date`; `null` title → 422. **No `status` here.** Editing title/description sets the sticky `*_manually_set` flags |
| `DELETE /goals/{id}` | Soft delete, un-links its tasks (`goal_id → null`), Notion untouched. **No undelete route** |
| `PATCH /goals/{id}/status` | Body `{status: open\|paused\|done\|dropped}`; enqueues Notion sync. Returns the goal |
| `GET /tasks?goal_id=` | Already exists (1.9). `TaskRead` has `title`, `due_date`, `status` (`open`/`done`), `urgency`, … |

**`GoalRead` today:** `id, title, description, status, source, horizon, target_date,
memory_record_id, created_at`. It does **not** include `title_manually_set` /
`description_manually_set` — needed for the pin (§1.5), so that's a small backend change.

**Frontend from F1.1 (`web/`) this builds on:** `api` (openapi-fetch + `authFetch`), `unwrap()` /
`ApiError` / `errorMessage()` (`lib/api/errors.ts`), `STALE_TIME.goals` (5 min) and `.tasks` (30 s)
plus a `queryKeys` object (`lib/api/query-config.ts`), a global `MutationCache` error toast, the
offline hooks `useIsOffline()` / `useIsOfflineFor()` (`lib/api/offline.ts`), `EmptyState`, the
design tokens in `globals.css`, and shadcn `button, card, form, input, label, separator, skeleton,
sonner` (Radix base, restyled). react-hook-form + zod are installed. The Goals page is a
placeholder `EmptyState`.

**F1.1 decisions that matter here (decisions-log 2026-09-26):** mutations pause while offline (the
"hold actions" choice), so F1.6 is the **first feature that has to show "Waiting to send"**; login
/ signup deliberately aren't mutations for that reason, but goal edits should be.

**Carried-over checks F1.6 can now do (N-41):** F1.1 couldn't live-test "token expires → one 401 →
one refresh → retry" because no screen called the API after boot. Goals does, so §9 re-checks it.

---

## 1. Answers to the open questions

### 1.1 Where goal details open → **side panel** (Tola, 2026-09-26)
Desktop (≥ 768px): a sheet from the right, 28rem wide, over a dimmed list. Mobile: a bottom drawer
(vaul, via shadcn `drawer`) with swipe-to-dismiss. The list keeps its place and scroll position
behind it. One shared `DetailPanel` component, reused by Tasks in F1.5.

### 1.2 Default list → **Active (open + paused), with a switch: Active | Done | Dropped | All**
The switch is a 4-option segmented control (shadcn `toggle-group`, single). Active sends
`?status=open&status=paused`; All sends no status filter. Paused rows get a small "Paused" label.

### 1.3 Linked tasks → **read-only list in the panel**
`GET /tasks?goal_id=<id>&items_per_page=50`. Header "3 tasks · 1 done", then rows with a done/open
icon, title and due date. No editing (that's F1.5). Not shown in create mode.

### 1.4 AI horizon guess → **"MyPA is suggesting…" + short re-check**
When a goal has `horizon: null` **and** was created less than 20 seconds ago, the horizon spot shows
"MyPA is suggesting…" (with a small spinner) and that goal's query re-fetches every 3 s. The label
stops when a horizon arrives or the 20 s pass; then the field just shows "Not set". This uses
`created_at`, so it works in the list and the panel without extra state. With no real LLM key
(N-12), the fallback is what you'll see locally.

### 1.5 Pin for fields you set by hand → **add the two flags to `GoalRead`**
Backend: add `title_manually_set: bool` and `description_manually_set: bool` to `GoalRead`
(`schemas/goal.py`). Frontend: a small `Pin` icon next to the title/description labels in the panel
with the tooltip "You set this — the assistant won't change it" (design-system §7.3). Then
`pnpm gen:api`.

### 1.6 ETag / 304 → **build the shared helper now, use it on the goal routes** (N-38)
See §3.2. F1.5 switches it on for tasks.

### 1.7 Changing status → **status menu on the row and in the panel**
A Radix `DropdownMenu` with radio items (Open / Paused / Done / Dropped). On the row it's the
status label (`Open ▾`); in the panel it sits next to the title.

### 1.8 Smaller calls I made (easy to flip — say if you want any changed)
- **Edits save with an explicit "Save" button** in the panel (react-hook-form, only changed fields
  are sent). Closing with unsaved changes asks "Discard changes?". Autosave-on-blur was the
  alternative — more magic, harder to undo.
- **Target date uses the browser's native date input**, not a date-picker library. It's accessible,
  gives phones their native picker, and adds nothing to the bundle.
- **URL keeps the view state**: `/goals?status=done&goal=<id>`. Refresh keeps your filter and
  open goal, and the Back button closes the panel.
- **Status change shows an "Undo" toast** ("Marked done · Undo"). Delete has no undo on the backend,
  so it's a confirm dialog instead ("Delete this goal? Its tasks stay, but lose the link.").
- **"Load more" button** at the end of the list (50 per page), not infinite scroll — simpler and
  keyboard-friendly. Goals lists are short; no virtualisation.
- **Horizon and source filters** from the API aren't exposed in F1.6. The PRD only asks for a flat
  list, and four status views are enough. Easy to add later.

---

## 2. Build order

1. Backend: `GoalRead` flags (§3.1) + ETag helper and goal routes (§3.2) + tests.
2. `pnpm gen:api` (backend running) → commit the new `openapi.json` / `schema.d.ts`.
3. shadcn components (§4) restyled onto the tokens.
4. Shared pieces: `DetailPanel`, `SourceBadge`, `PendingLabel`, `ConfirmDialog`, `useMediaQuery`,
   date formatting (§5).
5. Goal data layer: keys, queries, mutations with cache updates (§6).
6. Goal UI: page, filter, list, row, status menu, panel (create + edit), linked tasks (§7).
7. Tests (§8), then lint / typecheck / test / build + backend checks.
8. Live walkthrough (§9).
9. Office updates (§10).

---

## 3. Backend changes (small, both inside F1.6)

### 3.1 `schemas/goal.py`
`GoalRead` gains `title_manually_set: bool = False` and `description_manually_set: bool = False`.
Routes already select through `GoalRead`, so no route change. Update `tests/test_goals.py` where it
asserts the exact response shape.

### 3.2 ETag helper — new `core/utils/etag.py`
```python
def etag_for(payload: Any, user_id: Any) -> str:
    """Weak ETag over the JSON-encoded payload + the user's id."""

def not_modified_or_none(request: Request, etag: str) -> Response | None:
    """304 (with the same ETag) if If-None-Match matches, else None."""
```
- Hash: `sha256(json.dumps(jsonable_encoder(payload), sort_keys=True) + str(user_id))`, first 32
  hex chars, sent as `W/"<hash>"`. **The user id is part of the hash**, so two users with
  identical data (e.g. both empty lists) still never share a cached reply after a logout/login in
  the same browser.
- `read_goals` and `read_goal` take `request: Request, response: Response`, build their payload as
  today, then: compute the ETag; if it matches `If-None-Match`, return `Response(status_code=304,
  headers={"ETag": etag})`; otherwise set `response.headers["ETag"]` and return the payload.
  Return type becomes `dict | Response`.
- This works because B-06 already sends `Cache-Control: private, no-cache` on `/api/`: the browser
  keeps the reply, sends `If-None-Match` on the next request by itself, and turns a 304 back into a
  normal 200 for `fetch`. **No frontend code.**
- Why a helper per route and not a middleware: a middleware would have to buffer every response
  (and must never touch the future SSE stream). Two explicit call sites are clearer.
- Tests (`tests/test_etag.py`): 200 carries an ETag; the same ETag in `If-None-Match` → 304 with no
  body; a changed goal → a different ETag → 200; same payload for two users → different ETags.

---

## 4. UI kit additions

`pnpm dlx shadcn add sheet drawer dropdown-menu select textarea alert-dialog toggle-group tooltip`
(adds `vaul` for the drawer). Restyle each onto the tokens the same way F1.1 did: no dark variants,
16px text in inputs/textarea, 40px controls (44px on touch), `--radius-md`/`--radius-lg`, level-3
shadow on sheet/drawer/dialog, backdrop `oklch(0.235 0.012 75 / 0.32)`, motion per
design-system §6.2 (sheet `--dur-drawer` `--ease-drawer`; dialog 200 ms scale from 0.96; dropdown
150 ms from the trigger; no animation under `prefers-reduced-motion`).

---

## 5. Shared pieces (Tasks reuses all of them in F1.5)

| File | What it does |
|---|---|
| `src/lib/use-media-query.ts` | `useMediaQuery("(min-width: 768px)")` via `useSyncExternalStore` (server snapshot `false`) |
| `src/components/detail-panel.tsx` | `DetailPanel({ open, onOpenChange, title, children, footer })` → `Sheet` on desktop, `Drawer` on mobile. Title is the accessible dialog name; focus returns to the trigger on close (Radix) |
| `src/components/source-badge.tsx` | `SourceBadge({ source })` — tint + icon per design-system §3.3 (manual `PenLine`, conversation `MessageCircle`, email `Mail`, calendar `CalendarDays`, notion `FileText`). Label text always present (not colour alone) |
| `src/components/pending-label.tsx` | `PendingLabel({ kind: "send" \| "delete" })` — `Clock` icon + "Waiting to send" / "Waiting to delete" in `--ink-3` (design-system §7.6) |
| `src/components/confirm-dialog.tsx` | `ConfirmDialog` on `alert-dialog`: title, one sentence, a named destructive button ("Delete goal") + "Cancel" |
| `src/lib/format/date.ts` | `formatDay(isoDate)` → "Today" / "Tomorrow" / "Fri 3 Oct" / "3 Oct 2027" (other years), using `Intl.DateTimeFormat` and the user's timezone from the session. `isOverdue(isoDate)` for later use by Tasks |
| `src/lib/api/query-config.ts` | Extend `queryKeys` with `goals.all`, `goals.list(view)`, `goals.detail(id)`, `tasks.byGoal(id)` |

---

## 6. Goal data layer — `src/lib/goals/`

**`labels.ts`** — display names: status (`Open`, `Paused`, `Done`, `Dropped`), horizon
(`Short-term`, `Long-term`, `Not set`), and the four views (`active` → `["open", "paused"]`, `done`,
`dropped`, `all` → no filter).

**`form-schema.ts`** — zod schema for the panel form: `title` (trimmed, 1–255,
"Give the goal a title."), `description` (string, empty → `null`), `horizon`
(`"suggest" | "short_term" | "long_term"` in create mode, where `suggest` → `null`;
`"none" | "short_term" | "long_term"` in edit mode, where `none` → `null`), `targetDate`
(`""` → `null`, else `YYYY-MM-DD`). `toCreateBody(values)` and `toPatchBody(values, dirtyFields)`
— the patch body contains **only fields react-hook-form marks dirty**, so an untouched field is
never sent (matters for sticky flags: re-sending an unchanged title would set
`title_manually_set`).

**`queries.ts`**
- `useGoalsList(view)` — `useInfiniteQuery`, `items_per_page: 50`, `getNextPageParam` from
  `has_more`, `staleTime: STALE_TIME.goals`.
- `useGoal(id, { pollForHorizon })` — `useQuery`, seeded from any list page that already has the
  goal (`initialData` from the list cache, so the panel opens instantly). `refetchInterval` returns
  `3000` while `horizon === null && Date.now() - created_at < 20_000`, else `false` (§1.4).
- `useLinkedTasks(goalId)` — `GET /tasks?goal_id=…&items_per_page=50`, `staleTime:
  STALE_TIME.tasks`.
- Mutations — all go through the global `MutationCache` (error toast) and pause while offline:
  - `useCreateGoal` — optimistic: insert a temporary row (`id: "pending-<uuid>"`, `status: "open"`,
    `source: "manual"`, `created_at: now`) at the top of the `active` and `all` lists; on success
    replace it with the server row and seed `goals.detail`; on error remove it. If the current
    view is Done/Dropped, switch to Active so the new goal is visible.
  - `useUpdateGoal` — optimistic patch of the goal in `goals.detail` and in every cached list page
    (`setQueriesData` on `goals.all`); rollback on error; set the server row on success.
  - `useSetGoalStatus` — optimistic status change in all caches; on settle invalidate the lists
    (so a goal marked done leaves Active); success toast "Marked done · Undo" (Undo runs the same
    mutation with the previous status).
  - `useDeleteGoal` — on success remove from lists, drop `goals.detail`, and invalidate
    `tasks.byGoal` (the backend un-linked them).
- **"Waiting to send"**: `usePendingGoalIds()` reads `useMutationState({ filters: { status:
  "pending" } })` plus `isPaused` for goal mutations and returns the set of goal ids with a paused
  mutation → rows and the panel show `PendingLabel`. A pending create shows its temp row with
  "Waiting to send" at 70% opacity.

---

## 7. Goal UI — `src/components/goals/` + the page

**`app/(app)/goals/page.tsx`** stays a server component (keeps `metadata`) and renders
`<GoalsView />` (client).

**`goals-view.tsx`** — reads `status` and `goal` from `useSearchParams` (`status` defaults to
`active`; unknown values fall back to `active`). Header row: serif page title "Goals" on desktop
only (mobile has the tab bar label), the `GoalFilter`, and a primary "New goal" button (`Plus`
icon; on mobile a 44px icon+label button at the top right). Renders `GoalList` and the
`GoalPanel`. Opening a goal pushes `?goal=<id>`; "New goal" pushes `?goal=new`; closing removes the
param (router `replace` for filter changes, `push` for opening the panel so Back closes it).

**`goal-filter.tsx`** — `ToggleGroup` with Active / Done / Dropped / All; `aria-label="Show
goals"`. Changes are instant (no animation, design-system §6.2).

**`goal-list.tsx`** — states:
- Loading: 5 skeleton rows shaped like real rows.
- Error (whole list failed): inline message + "Try again" (the only full-area error, PRD §7).
- Empty, per view — Active/All: `EmptyState` "What are you working toward?" + "Add a goal and MyPA
  will connect related tasks to it." + [New goal]; Done: "Nothing finished yet."; Dropped:
  "Nothing dropped." (one plain sentence each, no action).
- Rows, then "Load more" while `hasNextPage` (button shows a spinner and keeps its width).

**`goal-row.tsx`** — a `<li>` with **two separate controls** (no button inside a button): the main
area is a button that opens the panel (accessible name = the title), and the `GoalStatusMenu`
trigger sits at the end. Layout (56px min, `--border` dividers, hover `--muted` on fine pointers):
title (`text-sm` 500, one line, ellipsis) with the description's first line under it in `--ink-2`
(ellipsis, hidden under 400px); target date (`formatDay`, tabular); horizon as plain text
("Short-term") or "MyPA is suggesting…"; `SourceBadge`; status label (with "Paused" in
`--warning`-outlined style so it stands out); `PendingLabel` when relevant. On mobile, date +
horizon + badge wrap to a second line.

**`goal-status-menu.tsx`** — `DropdownMenu` + `DropdownMenuRadioGroup`; trigger text is the status
+ `ChevronDown`; `aria-label="Status: Open. Change status"`. 44px hit area on touch.

**`goal-panel.tsx`** — `DetailPanel` in two modes:
- **Create** (`?goal=new`): title "New goal". Fields: Title, Description (textarea, 3 rows,
  grows), Horizon (`Select`: "Let MyPA suggest" (default) / Short-term / Long-term, hint: "MyPA
  guesses this from the title if you leave it."), Target date (native `type="date"`, optional,
  hint "Optional"). Footer: "Create goal" (primary) + "Cancel". On submit: create, close the panel,
  toast "Goal added".
- **Edit** (`?goal=<id>`): title = the goal's title. Top line: `GoalStatusMenu`, `SourceBadge`,
  "Added 3 Sep". Fields as above (Horizon options: Not set / Short-term / Long-term, or the
  "MyPA is suggesting…" line while §1.4 applies), with `Pin` icons beside Title/Description labels
  when the flags are set. Then `LinkedTasks`. Footer: "Save" (disabled until something changed) +
  "Cancel", and a quiet "Delete goal" text button on the left that opens `ConfirmDialog`.
  - A goal id that 404s (deleted elsewhere) or 403s → the panel shows "This goal isn't available
    any more." with a Close button, and the list is invalidated.
  - Server `detail` errors on save show inline above the footer, not only as a toast (the form
    stays filled — never lose work).

**`linked-tasks.tsx`** — skeleton (3 lines) while loading; "No tasks linked yet." when empty; else
the header count and up to 50 rows (`CheckCircle2` for done in `--success`, `Circle` for open,
title, `formatDay(due_date)`). Read-only; no links yet (Tasks has no panel until F1.5).

**Accessibility:** the list is a `<ul aria-label="Goals">`; every icon-only control has an
`aria-label`; status, horizon and source are always text, never colour alone; focus returns to the
row after the panel closes; the filter and menus are fully keyboard-driven (Radix).

---

## 8. Tests

**Frontend (Vitest + Testing Library + MSW)** — `src/components/goals/*.test.tsx`,
`src/lib/goals/*.test.ts`:
- List: first request is `status=open&status=paused&items_per_page=50`; switching to Done/Dropped/All
  changes the request and the URL; "Load more" fetches page 2; each empty state; skeleton while
  loading.
- Create: sends `horizon: null` for "Let MyPA suggest", `null` for an empty date; the temp row
  appears at once and is replaced by the server row; from the Done view it switches to Active.
- Horizon: a goal created < 20 s ago with `horizon: null` shows "MyPA is suggesting…" and
  re-fetches; the label goes when the horizon arrives; an older goal shows "Not set" and doesn't
  poll.
- Edit: only dirty fields are in the PATCH body (untouched title not sent); clearing the date sends
  `null`; unsaved changes → "Discard changes?"; a 422 shows inline and keeps the form.
- Status: the row menu calls `PATCH /goals/{id}/status`; the goal leaves the Active list; "Undo"
  restores it.
- Delete: needs confirmation; on success the row is gone and linked tasks are invalidated.
- Panel: `?goal=<id>` opens it on load; Back closes it; a 404 shows "isn't available any more".
- Pins show only when the flags are true. Linked tasks: count header, empty state.
- Offline: a create/edit while `onlineManager` is offline shows "Waiting to send" and completes
  once back online.
- `formatDay`: today / tomorrow / same year / other year.

**Backend (pytest)**: `tests/test_etag.py` (§3.2), `tests/test_goals.py` updated for the two new
`GoalRead` fields and for 304 on `GET /goals` and `GET /goals/{id}`.

**Checks:** `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`; backend `uv run pytest`,
`uv run ruff check`, `uv run mypy src` (no new errors over the D-07 baseline of 13).

---

## 9. Live verification

Backend on `:8000` (Postgres 5434 / Redis 6380, ARQ worker running so the horizon job can run),
web on `:3001` (N-40).

1. `pnpm gen:api` picks up the new `GoalRead` fields; typecheck passes.
2. Empty Active view shows the empty state; create 3 goals (one with "Let MyPA suggest"). With no
   real LLM key, "MyPA is suggesting…" shows, then falls back to "Not set" after ~20 s.
3. Open a goal → panel; edit title only → PATCH body has only `title`; the pin appears; reload keeps
   `?goal=<id>` open; Back closes it.
4. Status menu on a row → Done → leaves Active, shows in Done; Undo brings it back.
5. Link a task to a goal with curl (`POST /tasks` with `goal_id`) → the panel lists it with the
   count; delete the goal (confirm) → the task's `goal_id` is null in the DB.
6. **ETag**: DevTools → reload Goals twice → the second `GET /goals` is **304** through the Next dev
   proxy (confirm the proxy passes `If-None-Match`/`ETag`); edit a goal → next GET is 200 with a
   new ETag. Log in as another user in the same browser → no 304 carrying the first user's data.
7. **Token expiry (closes N-41 a):** backend with `ACCESS_TOKEN_EXPIRE_MINUTES=1`, wait, open a goal
   → one 401, one `/refresh`, the request retried, no visible glitch.
8. **Offline:** DevTools → Offline → edit a goal → "Waiting to send" + offline banner; back online →
   it saves, label clears. Slow 3G: skeletons show, nothing blank. (If the headless browser can't
   throttle again, do this by hand — N-41 b.)
9. 360px: rows wrap cleanly, the drawer opens from the bottom and swipes closed, 44px targets;
   keyboard: tab through filter → rows → status menus, open/close the panel with Enter/Esc, focus
   returns to the row.

---

## 10. Office updates when built

- `phase-tracker.md`: F1.6 status + verification; note N-38 half done (goals).
- `decisions-log.md`: sign-off, the §1 answers (logged at plan time — see below), build deviations.
- `open-items.md`: close B-07; update N-38 (goals done, tasks in F1.5); update N-41 (a) if closed.
- `session-notes.md`: session entry.

---

## 11. Not in F1.6

- Horizon / source filters, search, sorting options (not in the PRD for goals).
- Editing tasks from the goal panel or linking tasks from here (F1.5).
- Undo for delete (no backend undelete).
- Onboarding's goal checklist (F1.4) — it will reuse `SourceBadge`, `formatDay` and the form schema
  pieces where they fit.
- Playwright (starts with F1.4).
- ETag on tasks (F1.5 switches the helper on).
