# Feature F1.5 — Tasks view: implementation plan

Status: **PROPOSED 2026-09-26** — every question in §1 was answered by Tola in two question rounds
(all as recommended). The smaller calls in §1.8 are mine and easy to flip. **Built 2026-09-26**;
FullCalendar 7.1 chosen (§4), deviations and fixes in `decisions-log.md` 2026-09-26.
Written: 2026-09-26.
Branch: `feature/F1.5-tasks-view` (already created) from `feature/F1.6-goals-view@243dd18` (F1.6,
committed 2026-09-26, on top of F1.1's `00d3ef5`). F1.5 reuses F1.6's code.
Source of truth: `dumpbox/PRD-personal-assistant-frontend-mvp.md` §5.3, §7, §8, §9 (calendar
density); backend task rules from Features 1.8/1.9.
Visual rules: `project-manager/design-system.md` §3.3 (badges, urgency), §6.2 (motion), §7.1
(effort icons), §7.3 (lists + calendar), §7.4 (forms), §7.6 (states).

---

## 0. What I checked before writing this

**Backend task API (`backend/src/app/api/v1/tasks.py`, built in 1.8/1.9) — no new routes needed.**

| Route | Notes for the frontend |
|---|---|
| `POST /tasks` | Body `TaskCreate`: `title` (1–255), `description?`, `due_date?`, `urgency?` (`low`/`medium`/`high`), `effort_level?` (`deep_focus`/`light_focus`/`passive`), `goal_id?` (own, non-deleted goal, any status). `source` forced to `manual`. **An empty urgency is saved as `medium` straight away as a placeholder**; empty urgency/effort enqueue `guess_task_fields`. Filled fields are saved as sticky (`*_manually_set = true`) |
| `GET /tasks` | Paginated (`items_per_page` ≤ 100). Filters: `status` (**one** value: `open`/`done`), `urgency`, `source`, `due_from`, `due_to` (inclusive, 400 if reversed), `goal_id`. **Order: open first, then due date soonest first (no date last), then newest** |
| `GET /tasks/{id}` | 404 if deleted, 403 if not yours |
| `PATCH /tasks/{id}` | Only sent fields change. `null` clears `description`/`due_date`/`effort_level` and unlinks `goal_id`; `null` title/urgency → 422. Every edited field becomes sticky (incl. `goal_id`, even when unlinking). **No `status` here** |
| `DELETE /tasks/{id}` | Soft delete; Notion untouched; no undelete route |
| `PATCH /tasks/{id}/status` | `{status: open\|done}`; enqueues Notion sync |

**`TaskRead` today:** `id, title, description, due_date, status, source, urgency, effort_level,
memory_record_id, scheduled_event_id, goal_id, created_at`. **None of the five sticky flags**
(`title_/description_/urgency_/effort_level_/goal_id_manually_set`) — needed for pins and for the
"suggesting…" labels (§1.5).

**`scheduled_event_id` is only a Google Calendar event id** — no start/end time is stored, and
Scouring (1.12) isn't built, so no task has one today (§1.1).

**F1.6 code this reuses** (built, uncommitted): `DetailPanel` (sheet ≥ 768px / drawer below),
`SourceBadge`, `PendingLabel`, `ConfirmDialog`, `useMediaQuery`, `formatDay` / `isOverdue` /
`todayIn` (`lib/format/date.ts`), `useTimeZone`, shadcn `sheet, drawer, dropdown-menu, select,
textarea, alert-dialog, toggle-group, tooltip` (restyled), and patterns inside
`components/goals/`: `ManualPin` + `LabelRow` (goal-fields.tsx), `useCloseGuard` + `RootError`
(goal-panel.tsx), the "suggesting…" timer (horizon-text.tsx), optimistic list helpers and
`usePendingGoals` (lib/goals/queries.ts). Backend: `core/utils/etag.py` (`etag_for`,
`not_modified_or_none`) plus a private `_with_etag` wrapper in `api/v1/goals.py`.

**Library check.** npm today: `@fullcalendar/react` and `@fullcalendar/core` **7.1.0** (React
peer `^17 || ^18 || ^19`, needs `temporal-polyfill`), while `@fullcalendar/daygrid`,
`timegrid`, `interaction` are still **6.1.21**. v7 may have changed how plugins are packaged
(§4) — the build must confirm the working combination before writing calendar code.

**Carried-over items:** N-42 (the AI guess can land after the 20 s window) applies to tasks the
same way — accepted, same fix later. N-38: goals half done in F1.6; this plan does the tasks half.

---

## 1. Answers to the open questions

### 1.1 Calendar data → **due dates only, as all-day items** (Tola, 2026-09-26)
Tasks with a `due_date` appear on that day. Tasks with no due date don't appear on the calendar.
Scheduled time slots come with Scouring (1.12), which should then **store the slot's start/end on
the task** (new open item N-43 so 1.12's plan picks it up). No migration in F1.5.

### 1.2 Calendar layout → **desktop Month | Week, phone week agenda**
Desktop (≥ 768px): FullCalendar `dayGridMonth` (default) and `dayGridWeek` (all-day only, so a
time grid would be empty). Phone: `listWeek` — days as headings, tasks under them — with ‹ › and
"Today". Read-only (`editable: false`), `dayMaxEvents: true` so busy days collapse to "+N more"
(PRD §9).

### 1.3 List filters → **Open | Done | All switch + Source and Urgency dropdowns + Clear**
Open by default. The dropdowns are compact `Select`s ("Source: Any", "Urgency: Any"); a "Clear"
link appears when either is set. On phones they sit on a second line. The same filters apply to
the calendar.

### 1.4 Due grouping → **headings in the Open view only**
Overdue · Today · Tomorrow · Next 7 days · Later · No date, worked out client-side from the
already-sorted list (the backend sorts open tasks by due date, so headings never jump around
between pages). Overdue dates show "Overdue · 3 Oct" in `--danger` (word + colour). Done and All
stay plain lists. I used "Next 7 days" instead of "This week" so the heading doesn't depend on
which day a week starts on.

### 1.5 Pins and "suggesting…" → **add the five flags to `TaskRead`**
Backend: add the five `*_manually_set` booleans to `TaskRead`. Frontend:
- Pins (shared `ManualPin`) beside Title, Description, Urgency, Effort and Goal when set.
- "MyPA is suggesting…" for **urgency** while `!urgency_manually_set` and the task is under 20 s
  old, and for **effort** while `effort_level === null && !effort_level_manually_set` and under
  20 s old. The task re-fetches every 3 s during that window, like the goal horizon.

### 1.6 Tasks ↔ goals → **goal dropdown + goal name on rows + click-through from goals**
- Task panel: a "Goal" `Select` listing open + paused goals and "No goal". If the task is linked
  to a done/dropped goal, that goal is also listed as the current value ("Launch v1 · Done").
- Rows: the goal's name in `--ink-3` under the title ("↳ Launch ClientPal").
- F1.6's `LinkedTasks` rows become links to `/tasks?task=<id>`.
- Goal names come from a new `useGoalTitles()` (§6) that loads all goals once (goals change
  rarely; ETag makes re-checks nearly free).

### 1.7 Marking done → **checkbox on each row + in the panel, Undo, fades out**
A round checkbox at the start of every row (44px hit area on touch) and at the top of the panel.
Ticking calls `PATCH /tasks/{id}/status` optimistically. In the Open view the row shows ticked +
struck through for ~1.2 s, then leaves the list (with `prefers-reduced-motion`: no fade, just
removed after the pause). Toast "Marked done · Undo" (5 s) puts it back. Unticking a done task
works the same way in reverse. Offline: the row stays ticked with "Waiting to send" and only
leaves once the change is sent.

### 1.8 Smaller calls I made (easy to flip)
- **Due date: native date input plus quick chips** "Today · Tomorrow · Next week" under it.
  design-system §7.4 suggested typing "next friday"; chips cover the common cases without a
  date-parsing library. (Logged as a small deviation.)
- **Urgency and Effort selects** default to "Let MyPA suggest" in create mode (sends `null`);
  edit mode offers Low/Medium/High (urgency can't be cleared — the backend rejects `null`) and
  Not set/Deep focus/Light focus/Passive.
- **Same panel behaviour as Goals** (decisions-log 2026-09-26): explicit Save, only changed
  fields sent, edit panel stays open after Save, create closes it; "Discard changes?" guard;
  confirm dialog for delete ("Delete this task? This can't be undone."). Server errors inline.
- **URL keeps the view**: `/tasks?view=list|calendar&status=open&source=email&urgency=high&task=<id>`
  plus `&cal=month|week&date=YYYY-MM-DD` for the calendar. Back closes the panel.
- **Calendar loads its visible range** (`due_from`/`due_to`, 100 per page, following `has_more`)
  with the Source/Urgency filters and the status switch (All = both statuses). Done tasks show
  faded and struck through.
- **"Load more"** at the list's end, 50 per page, like Goals.
- **Refactor, not copy:** the goal-only pieces Tasks also needs move to shared files (§5). The
  query layers stay separate — tasks and goals have different filters, sorts and statuses.

---

## 2. Build order

1. Backend: `TaskRead` flags; move `_with_etag` into `core/utils/etag.py` as `with_etag` and use it
   on the goal **and** task list/detail routes; tests (§3).
2. `pnpm gen:api` (backend running) → commit the new `openapi.json` / `schema.d.ts`.
3. Confirm the FullCalendar package combination (§4); add it.
4. Shared refactor out of `components/goals/` (§5); goals tests must still pass untouched.
5. Task data layer (§6).
6. Task UI: page, view switch, filters, list with due groups, row, done checkbox, panel,
   calendar (§7); make `LinkedTasks` rows link to Tasks.
7. Tests (§8), then lint / typecheck / test / build + backend checks, and `pnpm analyze` to confirm
   FullCalendar isn't in the first-load bundle.
8. Live walkthrough (§9).
9. Office updates (§10).

---

## 3. Backend changes (small)

### 3.1 `schemas/task.py`
`TaskRead` gains `title_manually_set`, `description_manually_set`, `urgency_manually_set`,
`effort_level_manually_set`, `goal_id_manually_set` (all `bool = False`). Update the
response-shape assertions in `tests/test_tasks.py`.

### 3.2 ETag on tasks (finishes N-38)
- Move `api/v1/goals.py::_with_etag` into `core/utils/etag.py` as
  `with_etag(request, response, payload, user_id) -> dict | Response` (one helper, two routers).
  `goals.py` switches to it (behaviour unchanged — its tests prove it).
- `read_tasks` and `read_task` take `request: Request, response: Response` and return
  `with_etag(...)`. Return type `dict | Response`.
- Tests: `tests/test_tasks.py` — `GET /tasks` and `GET /tasks/{id}` send an `ETag`; matching
  `If-None-Match` → bodyless 304; a changed task → new ETag. `tests/test_etag.py` covers the moved
  helper.

---

## 4. FullCalendar

- **Check first** (don't guess): read the v7 packages' README/changelog in `node_modules` after a
  trial install. If v7 ships dayGrid/list views inside `@fullcalendar/core` (or as v7 plugins),
  use v7 (`@fullcalendar/react@7`, `temporal-polyfill`). If v7 still needs the 6.1 plugins and
  they don't work together, pin everything to the latest **6.1.x** (React 19 is supported there
  too). Log whichever was chosen.
- Needed views: day-grid month + week, and list week. All MIT (no premium plugins).
- **Loaded late** (decided 2026-09-25): `task-calendar.tsx` is imported with
  `next/dynamic(..., { ssr: false, loading: CalendarSkeleton })`, so FullCalendar only downloads
  when someone opens the Calendar view. `pnpm analyze` must show it outside the `/tasks` first
  load.
- **Styling:** override FullCalendar's `--fc-*` CSS variables with the design tokens in a
  `task-calendar.css` imported by the lazy component (so it lazy-loads too): `--canvas` page,
  `--border` lines, today cell `--accent-soft`, toolbar buttons styled like our secondary buttons,
  Instrument Sans, tabular numbers. Events are rendered with `eventContent` as our own small
  component: title + a filled `--danger` dot for high urgency; open tasks as `--accent-soft`
  blocks with `--accent-ink` text, done tasks faded + struck through.
- The toolbar is ours, not FullCalendar's (so it matches the list's controls): ‹ › Today, the
  month/year title, and the Month | Week switch on desktop. Driven through the calendar API ref.
- Clicking an event opens the task panel (`?task=<id>`). `firstDay` from the browser locale;
  timezone from the session (`useTimeZone`).

---

## 5. Shared refactor (out of `components/goals/`)

| New shared file | Moved from | Used by |
|---|---|---|
| `src/components/field-label.tsx` (`ManualPin`, `LabelRow`) | `goals/goal-fields.tsx` | goal + task fields |
| `src/components/panel-form.tsx` (`useCloseGuard`, `RootError`) | `goals/goal-panel.tsx` | goal + task panels |
| `src/components/suggesting.tsx` (`useGuessWindow(createdAt, windowMs)`, `SuggestingLabel`) | `goals/horizon-text.tsx` (generalised: "is this item still inside its AI-guess window?", re-rendering itself when the window ends) | goal horizon, task urgency/effort |
| `src/lib/api/list-cache.ts` — only if the goal and task optimistic helpers turn out identical after writing the task ones; otherwise leave them separate | `goals/queries.ts` | — |

Goal components import from the new files. **No behaviour change for Goals**; its existing tests
are the proof.

---

## 6. Task data layer — `src/lib/tasks/`

**`labels.ts`** — `Task = components["schemas"]["TaskRead"]`; labels for status, urgency (`Low`,
`Medium`, `High`), effort (`Deep focus` `Brain`, `Light focus` `Feather`, `Passive` `Headphones`),
views (`open` → `status=open`, `done`, `all` → no status), source options; `parseTaskSearch()`
turning URL params into a typed filter object (unknown values fall back to defaults).

**`due-groups.ts`** — `dueGroup(task, today)` → `overdue | today | tomorrow | next7 | later | none`
and `groupTasks(tasks, today)` for the Open view. Pure functions, unit-tested.

**`form-schema.ts`** — zod: `title` (1–255), `description`, `dueDate` (`""` → `null`), `urgency`
(`suggest|low|medium|high` create / `low|medium|high` edit), `effort` (`suggest|none|…`), `goalId`
(`"none"` → `null`). `toCreateBody`, `toPatchBody(values, dirtyFields)` — only dirty fields sent
(every sent field becomes sticky on the backend, so an untouched one must never be sent).

**`queries.ts`**
- Keys (extend `queryKeys.tasks`): `all`, `lists`, `list(filters)`, `calendar(range, filters)`,
  `detail(id)`, existing `byGoal(goalId)`.
- `useTasksList(filters)` — infinite, 50 per page, `staleTime: STALE_TIME.tasks`.
- `useTask(id)` — seeded from list caches; `refetchInterval` 3 s while inside the guess window
  and urgency/effort are still unguessed (§1.5).
- `useCalendarTasks(range, filters)` — fetches every page for the visible range (stops when
  `has_more` is false; a safety cap of 10 pages = 1,000 tasks, beyond which it shows "Showing the
  first 1,000 tasks").
- Mutations (paused offline, global error toast): `useCreateTask` (optimistic temp row in the
  matching list; if the current filters would hide it, switch to Open with no filters),
  `useUpdateTask` (optimistic in lists only, detail on success — the F1.6 rule), `useSetTaskStatus`
  (optimistic; the delayed removal from Open in §1.7; Undo), `useDeleteTask`.
- Cross-cache: any change to a task's `goal_id` or status invalidates `tasks.byGoal` for the old
  and new goal; **deleting a goal (F1.6's `useDeleteGoal`) also invalidates `tasks.lists` and
  `tasks.detail`**, since those tasks just lost their link.
- `usePendingTasks()` — like `usePendingGoals`, for "Waiting to send"/"Waiting to delete".

**`src/lib/goals/queries.ts`** — add `useGoalTitles()`: all goals (every status), fetched page by
page (100 per page) into a `Map<id, {title, status}>`, `staleTime: STALE_TIME.goals`. Used for
row goal names and the goal dropdown.

---

## 7. Task UI — `src/components/tasks/` + the page

**`app/(app)/tasks/page.tsx`** stays a server component (keeps `metadata`) rendering
`<TasksView />`.

**`tasks-view.tsx`** — reads the URL (§1.8). Header: "Tasks" (serif, desktop only), a List |
Calendar segmented control (`aria-label="Show tasks as"`), and "New task". Second row:
`TaskFilters`. Body: `TaskList` or the lazy `TaskCalendar`. Plus `TaskPanel`. Panel open/close
uses `push`/`replace` exactly like `GoalsView`, and focus returns to whatever opened it.

**`task-filters.tsx`** — Open | Done | All `ToggleGroup`, Source `Select`, Urgency `Select`,
"Clear". All changes instant.

**`task-list.tsx`** — skeleton (6 rows); whole-list error with "Try again"; empty states:
- Open, no filters: `EmptyState` "A clear list." + "Tasks from your email, calendar and chats
  will appear here, or add one yourself." + [New task] (design-system §7.6).
- Done: "Nothing finished yet." · All: same as Open.
- Any view with Source/Urgency set: "No tasks match these filters." + [Clear filters].
- Open view: due-group headings (`<h3>` inside the list, sticky under the header on scroll).
- "Load more".

**`task-row.tsx`** — `<li>` with three separate controls (no nested buttons): `DoneCheckbox`, a
main button that opens the panel (name = title), nothing else interactive. Content: title
(one line) + goal name under it; due (`formatDay`, "Overdue · …" in `--danger`); `SourceBadge`;
effort icon (with `aria-label`); urgency dot (high = filled `--danger` dot, medium = `--warning`
outline dot, low = nothing — design-system §3.3); `PendingLabel`; "MyPA is suggesting…" when in
the guess window. 56px min height; on phones the meta wraps to a second line.

**`done-checkbox.tsx`** — a Radix `Checkbox` (add shadcn `checkbox`, restyled: round, 20px visual,
44px hit area on touch, `--accent` when checked), `aria-label="Mark “<title>” done"` /
"… not done".

**`task-panel.tsx`** — `DetailPanel`:
- **Create** (`?task=new`): Title, Description, Due date (+ chips), Urgency, Effort, Goal. "Create
  task" / "Cancel".
- **Edit** (`?task=<id>`): top line `DoneCheckbox`, `SourceBadge`, "Added 3 Sep" (+ "Scheduled in
  your calendar" if `scheduled_event_id` is set — text only until 1.12). Same fields with pins and
  suggesting labels. Footer: Save / Cancel / "Delete task".
- A task that 404s/403s → "This task isn't available any more."

**`task-calendar.tsx`** (lazy) + `calendar-toolbar.tsx` + `task-calendar.css` — §4. Empty range:
a quiet line under the toolbar "No tasks due in this period." (the grid still shows).

**`components/goals/linked-tasks.tsx`** — each row becomes a `next/link` to `/tasks?task=<id>`.

**Accessibility:** list `<ul aria-label="Tasks">` with group headings; every icon has text or an
`aria-label`; urgency/effort/status never colour alone; the calendar's events are buttons with
names ("Send proposal, due Fri 3 Oct, high urgency"); keyboard: filters → rows → checkbox /
open, Enter/Esc for the panel.

---

## 8. Tests

**Frontend (Vitest + Testing Library + MSW)** — `components/tasks/*.test.tsx`,
`lib/tasks/*.test.ts`:
- List: first request `status=open&items_per_page=50`; switching Done/All, Source, Urgency updates
  the request and the URL; Clear resets; "Load more"; every empty state incl. "no tasks match".
- Due groups: correct headings across a page boundary; `dueGroup` for each bucket at timezone
  edges (user timezone ≠ UTC); no headings in Done/All.
- Done checkbox: optimistic tick → `PATCH /status` → leaves Open after the pause; Undo restores;
  offline tick shows "Waiting to send" and stays.
- Create: `null` for "Let MyPA suggest" urgency/effort; date chips fill the date; goal dropdown
  sends `goal_id`; filters that would hide the new task are cleared.
- Suggesting: a new task shows "MyPA is suggesting…" for urgency/effort and re-fetches; a
  hand-set urgency never shows it; the label ends after the window.
- Edit: only dirty fields sent; unlinking the goal sends `goal_id: null`; urgency can't be set
  empty; pins show only for true flags; a done/dropped linked goal appears as the current value.
- Goal names on rows; deleting a goal invalidates task lists; `LinkedTasks` links to
  `/tasks?task=<id>`.
- Calendar (FullCalendar mocked at the module boundary, since jsdom can't lay it out): the range
  request uses `due_from`/`due_to` and the filters, pages through `has_more`, and an event click
  opens the panel. The desktop/phone view choice is tested through `useMediaQuery`.
- Goals regression: the existing goals tests pass unchanged after the refactor.

**Backend (pytest):** `TaskRead` flags; ETag/304 on both task routes; goals ETag tests still pass
with the moved helper.

**Checks:** `pnpm lint`, `typecheck`, `test`, `build`, `analyze` (FullCalendar outside the first
load); backend `uv run pytest`, `ruff check`, `mypy src` (no new errors over the D-07 baseline of
13).

---

## 9. Live verification

Backend `:8000` with the ARQ worker, web `:3001` (N-40).

1. `pnpm gen:api` picks up the new `TaskRead` fields; typecheck passes.
2. Empty state → create 6 tasks with mixed due dates (overdue, today, tomorrow, +3 days, +20 days,
   none), sources set via curl for variety, one linked to a goal. Groups and order are right;
   "Overdue" is red with the word; the goal name shows on its row.
3. Leave urgency/effort on "Let MyPA suggest" → "suggesting…" shows, then (no LLM key, N-12) urgency
   stays Medium and effort Not set after ~20 s.
4. Tick a task → it fades out of Open; Undo → back; check `status` in the DB after each.
5. Edit only the title → PATCH has only `title`; pin appears; unlink the goal → `goal_id` null and
   the goal's panel no longer lists it; open a task from the goal panel → lands in Tasks with it open.
6. Filters: Source = email, Urgency = high → URL and request update; Clear.
7. Calendar (desktop): month shows tasks on their due days, "+N more" on a crowded day (seed ~6 on
   one day); Week view; click opens the panel. Network tab: FullCalendar chunks load only now.
8. Calendar (360px): week agenda with ‹ › and Today; the month grid is never shown.
9. ETag: reload twice → second `GET /tasks` is 304 through the proxy; after an edit → 200 new ETag.
10. Offline: tick + edit offline → "Waiting to send" + banner; back online → both saved.
11. Keyboard: filters → view switch → rows → checkbox; the calendar's events reachable by Tab.

---

## 10. Office updates when built

- `phase-tracker.md`: F1.5 status + verification; N-38 fully done.
- `decisions-log.md`: sign-off, the §1 answers (logged at plan time), FullCalendar version chosen,
  build deviations.
- `open-items.md`: close B-08 and N-38; add N-43 (1.12 must store the scheduled slot on the task).
- `design-system.md` §7.4: replace the "next friday" line with the date-chips approach.
- `session-notes.md`.

---

## 11. Not in F1.5

- Drawing Scouring's scheduled time slots (1.12 — needs stored start/end, N-43).
- Drag-and-drop rescheduling (PRD non-goal, parked P-08).
- Due-date range filter in the list UI, search, sort options.
- Bulk actions (tick many, delete many).
- Typing natural-language dates ("next friday").
- Playwright (starts with F1.4).
