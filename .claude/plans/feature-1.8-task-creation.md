# Feature 1.8 — Task creation from context: implementation plan

Status: **BUILT 2026-09-24** (signed off with all four recommendations). Uncommitted on `feature/1.8-task-creation`.

**How the build differed from this plan:**
- `manual_create_flags` (§8.1) was not kept. The two create-time flags are set inline in `write_task`, because it had one caller and mypy rejected `**dict[str, bool]`.
- Both PATCH routes pass `return_as_model=True` to `crud_tasks.update()`. Without it, FastCRUD 0.19.2 returns `None` and the route 500s. The live walkthrough found this, and the 1.7 `/status` route already had the bug.
- Test counts: 359 total (276 before + 83 new).
Written: 2026-09-24.
Branch to create: `feature/1.8-task-creation`, from `feature/1.7-notion-ingestion@024e850`.

---

## 0. What I checked before writing this

I re-read the real code and the installed packages instead of trusting the brief. Here is what I found.

**Git.** `git log --oneline --graph --all` shows one straight line of history:
`71ae606 → 4feb52f → f712880 → 67d61a5 → ccf90a7 → b33c1bd → 024e850`. The current branch is
`feature/1.7-notion-ingestion` at `024e850`, and the working tree is clean. So the new branch goes
straight on top of `024e850`.

**Alembic tip.** I read every file's `revision` / `down_revision`. The chain is
`ffc94ea56c76 → b1e4f2a9c7d3 → b4020f135620 → 19fcd1375166 → a1d91b329ac8 → 116b6b923450 →
d4f8b2a6c910 → 65a11312d511`. **`65a11312d511` is still the tip.**

**Installed library versions:** fastcrud 0.19.2, arq 0.26.3, SQLAlchemy 2.0.41, pydantic 2.12.5,
sentence-transformers 6.0.1, numpy 2.5.3.

**How FastCRUD 0.19.2 really behaves** (I read the source in `.venv/Lib/site-packages/fastcrud/`):

| Question | Answer from the source | What it means for us |
|---|---|---|
| What does `delete()` do? | If the model has both `is_deleted` and `deleted_at`, it runs an `UPDATE` that sets `is_deleted=True` and `deleted_at=now(UTC)`. Otherwise it hard-deletes. (`fast_crud.py` ~line 2850) | Adding the two columns is enough to make `crud_tasks.delete()` a soft delete. `db_delete()` still hard-deletes. |
| Do `get()`, `get_multi()`, `count()`, `update()` hide deleted rows by themselves? | **No.** None of them look at `is_deleted`. They only apply the filters you pass. | **Every** task query must pass `is_deleted=False` itself. Nothing does it for us. |
| What does `update()` do if nothing matches? | It calls `count()` first and raises `NoResultFound` if the count is 0. | We can make an update conditional (e.g. `urgency_manually_set=False`) and treat `NoResultFound` as "skip". |
| What sorting does `get_multi()` support? | Only plain column names with `"asc"`/`"desc"`. No `CASE`, no `NULLS LAST`. | See §7.2 for how the default order still works. |
| Filter operators? | `__gt`, `__gte`, `__lt`, `__lte`, `__ne`, `__in`, `__or`, etc. `__or` is per column only. | `due_date__gte` / `due_date__lte` work for the date range. The dedup query (open **or** recently done **or** recently deleted) spans several columns, so it needs plain SQLAlchemy (§8.2). |
| Pagination helpers? | `from fastcrud import compute_offset, paginated_response, PaginatedListResponse` all exist. `paginated_response` returns `data`, `total_count`, `has_more`, `page`, `items_per_page`. | First real use in this codebase. |

**Other things I confirmed in the code:**
- `SoftDeleteMixin` already exists in `core/db/models.py`, with `deleted_at` as
  `DateTime(timezone=True)` (so the 1.7 naive-datetime bug can't happen here). Nothing uses it yet.
  Its `is_deleted` has no `server_default`, so the migration must add one (existing rows need a value).
- The original `tasks` migration (`b1e4f2a9c7d3`) gave `urgency_manually_set` a
  `server_default=sa.text("false")`. The new flag columns will copy that.
- `ExtractedTaskCandidate.urgency` defaults to `"medium"`, so an extracted candidate **always** has
  an urgency. This matters for "fill blanks" (§8.3).
- `_retry_delay_seconds` in `core/integrations/jobs.py` is already imported by
  `core/notion/jobs.py` and `core/telegram/jobs.py`. The new job will reuse it the same way.
- No route in this codebase uses the `@cache` decorator (only the template's examples inside
  `core/utils/cache.py`). I am **not** adding caching to the task routes, to match the codebase.

---

## 1. Answers to the open questions

These are my recommendations. Tola makes the final call on each one.

### Q1. Should `PATCH /tasks/{id}` accept `status`?
**Recommendation: No.** `status` stays only on `PATCH /tasks/{id}/status`.

Why:
- There is then exactly **one** route that changes status, so exactly one place that enqueues
  `sync_status_to_notion`. There's no way to forget the Notion sync on a second path.
- "Mark done" and "edit the task" are separate actions in the UI anyway (a checkbox vs. an edit form).
- It keeps the sticky-flag logic simple: `PATCH /tasks/{id}` only handles the content fields.

What changes: `status` is removed from `TaskUpdate`. Sending `status` to `PATCH /tasks/{id}` then
returns 422 (because of `extra="forbid"`), which makes the mistake obvious.

If Tola prefers Yes: `PATCH /tasks/{id}` would accept `status` and enqueue `sync_status_to_notion`
**only when the status actually changed**. It's about 5 extra lines and one extra test.

### Q2. One shared title/description sticky flag, or one per field?
**Recommendation: one flag per field**, `title_manually_set` and `description_manually_set`.

Why: a user often fixes only one of the two. Example: they fix a typo in a Notion task's title, and
later add more detail to the same Notion line. With one shared flag, the typo fix would also freeze
the description, and the new detail would be lost. With one flag per field, only the title is
frozen. This also matches the existing pattern (`urgency_manually_set`, `effort_level_manually_set`):
one flag per field. The cost is one extra boolean column.

### Q3. Title embeddings: work them out on the fly, or store them?
**Recommendation: work them out on the fly. Don't store them.** This keeps the 2026-09-06 decision
("only conversation/email/Notion summaries get stored embeddings") as it is, so there's nothing to
raise with Tola there.

How to keep it cheap:
1. **Only do it when it's needed.** The dedup step runs only when an extraction gives back at least
   one candidate with confidence ≥ 0.7. Most emails and chat messages don't, so they cost nothing
   extra.
2. **Embed in batches.** Add one small function, `embed_texts(texts: list[str]) -> list[list[float]]`,
   next to `embed_text` in `core/llm/embedding_model.py`. It calls `_model.encode(list_of_texts)`
   once in a worker thread. Encoding 300 short titles in one batch on CPU takes well under a second.
   Doing them one at a time (300 separate thread hops) would take a few seconds.
3. **Put a limit on the list.** Compare against at most `TASK_DEDUP_MAX_EXISTING_TASKS` (default 500)
   of the user's tasks, newest first. If the limit is reached, log a warning.

Cost on a big onboarding backlog: say 200 ingested items, 40 of which produce a confident task, and
the user has 300 tasks. Then there are about 40 batch-encodes of about 300 titles each, roughly 40 × <1s.
That's small next to the 200 `high`-tier LLM calls the same onboarding run already makes, and far
inside the 1800s onboarding timeout.

### Q4. LLM tier for the manual-create guess job
**Recommendation: `medium`.**
- `low` is Ollama, which isn't installed (open item N-11), so the call would always fail.
- `high` is more than this needs. Guessing urgency/effort from one short task title is a much smaller
  job than full memory extraction.
- `medium` is already used for exactly this kind of small, low-stakes call (goal synthesis in 1.5,
  chat replies in 1.6). A wrong guess is cheap here: it's only a default the user can see and change.

### Q5. Things in the code that don't match the brief (flagged, not hidden)

1. **`determine_desired_checked_state` has a hidden bug once soft delete exists.** Today it returns
   `False` as soon as **any** linked item is missing or not done. After this feature, a deleted task
   still has its link row, so one deleted task on a Notion line would stop that line's checkbox from
   ever being ticked again, even when every remaining task is done. Fix in §10.3: deleted tasks are
   ignored when deciding the checkbox.
2. **`core/notion/jobs.py::_active_notion_user_ids` should NOT hide deleted tasks.** It's not really a
   "task read". It asks "has this user done anything lately?". Deleting a task *is* activity, and
   FastCRUD's soft delete runs an `UPDATE` that bumps `updated_at` (via the column's `onupdate`). So a
   delete correctly counts as activity. I recommend leaving this query unchanged and saying why in a
   comment. This is a deliberate exception to "every read hides deleted tasks", so it's logged as a
   decision.
3. **There is no `completed_at` column.** "Done within the last 60 days" has to use `updated_at` as a
   stand-in (a task becomes done through an update, so `updated_at` is set). Side effect: editing an
   old done task restarts its 60-day window. I recommend accepting this rather than adding a
   `completed_at` column (which would need a backfill and changes to every status write path).
4. **Urgency can't be "filled in" by dedup.** Both the existing task (column default `"medium"`) and
   the candidate (schema default `"medium"`) always have an urgency, so "empty" never happens for it.
   The fields that can be filled are `due_date`, `description`, `effort_level` (§8.3).
5. **`due_date` has no sticky flag.** If a user clears a due date in the app, a later email that
   mentions the same task with a date can fill it back in. I think that's acceptable (the email really
   does carry new information), but it's worth knowing. Logged as a non-blocking open item.
6. **`TaskCreate` can't tell "left empty" from "chose medium" today.** It inherits
   `urgency: Urgency = "medium"` from `TaskBase`. It needs its own fields where `urgency` and
   `effort_level` default to `None` (§5).
7. **A rewritten Notion line whose only link is a deleted task.** If the user deletes a task and then
   rewrites that Notion line a lot, the classifier might call it "updated" (not "no longer applies +
   a new item"). The update then does nothing (it's aimed at a deleted task), so no new task appears.
   This is a known trade-off of "the classifier still sees the deleted task". Logged as a non-blocking
   open item so it can be watched once real LLM output exists.
8. **Deleting the last open task on a Notion line doesn't tick the Notion checkbox,** even if every
   other task on that line is done. That's correct under "deleting never changes Notion". The checkbox
   catches up the next time any sibling task's status changes.
9. **`_update_item` today doesn't check that the task exists.** If the LLM returns a made-up
   `item_id`, `crud_tasks.update()` raises `NoResultFound` and the whole block's transaction rolls back.
   The new read-first logic (§10.2) turns that into a quiet no-op for tasks. This is a small, welcome
   side effect. I'm mentioning it so it isn't a surprise.

---

## 2. Summary of the build (in order)

| Step | What | Files |
|---|---|---|
| 1 | Branch | — |
| 2 | Migration + model | `src/migrations/versions/c3a7e19d52f8_add_task_soft_delete_and_sticky_flags.py` (new), `src/app/models/task.py` |
| 3 | Config | `src/app/core/config.py` |
| 4 | Schemas | `src/app/schemas/task.py` |
| 5 | CRUD | `src/app/crud/crud_tasks.py` (no code change, docstring only) |
| 6 | Core task logic | `src/app/core/tasks/__init__.py`, `sticky.py`, `dedup.py`, `jobs.py` (all new); `src/app/core/llm/task_field_guess.py` (new); `src/app/core/llm/embedding_model.py` (add `embed_texts`) |
| 7 | Routes | `src/app/api/v1/tasks.py` |
| 8 | Extraction pipeline | `src/app/core/llm/extraction.py` |
| 9 | Worker | `src/app/core/worker.py` |
| 10 | Notion paths | `src/app/core/notion/persistence.py`, `edit_gate.py`, `completion_sync.py`, `jobs.py` (comment only) |
| 11 | Tests | see §12 |
| 12 | Verify + update `project-manager/` + `erd.md` | see §13 |

---

## 3. Migration + model

### 3.1 New migration: `c3a7e19d52f8_add_task_soft_delete_and_sticky_flags.py`
(The revision id is only a suggestion. Any fresh 12-hex id works, as long as `down_revision` is right.)

- `revision = "c3a7e19d52f8"`, `down_revision = "65a11312d511"`.
- Written by hand, like every other migration here. The docstring notes that.

`upgrade()` adds five columns to `tasks`:

| Column | Type | Null | Server default |
|---|---|---|---|
| `deleted_at` | `sa.DateTime(timezone=True)` | yes | none |
| `is_deleted` | `sa.Boolean()` | no | `sa.text("false")` |
| `effort_level_manually_set` | `sa.Boolean()` | no | `sa.text("false")` |
| `title_manually_set` | `sa.Boolean()` | no | `sa.text("false")` |
| `description_manually_set` | `sa.Boolean()` | no | `sa.text("false")` |

The `server_default` on the four booleans is required: `tasks` may already have rows, and a
`NOT NULL` column can't be added to them without a default.

`downgrade()` drops the five columns in reverse order.

**No new index.** Every task query already filters by `user_id` first (`ix_tasks_user_id` exists),
and one user's task list is small, so an index on the low-variety `is_deleted` column wouldn't help.
If the list endpoint ever turns out slow on real data, the fix is a composite
`(user_id, is_deleted, status)` index in a later migration.

### 3.2 `src/app/models/task.py`
- Class line becomes `class Task(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):`
  (import `SoftDeleteMixin` from `..core.db.models`). This reuses the existing mixin instead of
  writing the columns inline, as the global convention asks.
- Add three fields right after `urgency_manually_set`, in the same style:
  ```
  effort_level_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
  title_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
  description_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
  ```
- Update the class docstring. It should say there are four sticky flags now (one per field), what
  they do, and that tasks are soft-deleted. Every read must pass `is_deleted=False`, **except** the
  Notion paths and the dedup query, which see deleted tasks on purpose (§10, §8).

Dataclass field order is fine: all mixin fields are `init=False` or have defaults, the same as
`TimestampMixin` today.

---

## 4. Config — `src/app/core/config.py`

Add one new settings mixin, following the "one class per concern" convention, and add it to the
`Settings(...)` base list:

```
class TaskSettings(BaseSettings):
    # Near-duplicate skip for extracted tasks (email/conversation/calendar only — Notion dedups
    # via notion_block_link). Decided 2026-09-24.
    TASK_DEDUP_SIMILARITY_THRESHOLD: float = 0.85
    TASK_DEDUP_LOOKBACK_DAYS: int = 60
    # Upper bound on how many existing tasks one dedup pass compares against (newest first).
    TASK_DEDUP_MAX_EXISTING_TASKS: int = 500
```

The ARQ `max_tries` for the new job stays a module constant in `core/tasks/jobs.py`
(`TASK_FIELD_GUESS_MAX_TRIES = 3`), matching the existing `ONBOARDING_MAX_TRIES` precedent. It's not
an env setting.

---

## 5. Schemas — `src/app/schemas/task.py`

| Schema | Change |
|---|---|
| `TaskBase` | No change. |
| `Task` (internal) | Also inherit `PersistentDeletion` (from `core/schemas.py`). Add `effort_level_manually_set: bool = False`, `title_manually_set: bool = False`, `description_manually_set: bool = False`. |
| `TaskRead` | No change. Deleted tasks are never returned, so `is_deleted`/`deleted_at` aren't needed. The flags stay internal. |
| `TaskCreate` | **Rewritten to stop inheriting `TaskBase`** (see Q5 item 6). Its own fields: `title` (same `Annotated` rules as `TaskBase`), `description: str \| None = None`, `due_date: date \| None = None`, `urgency: Urgency \| None = None`, `effort_level: EffortLevel \| None = None`. Keeps `model_config = ConfigDict(extra="forbid")`. Docstring: `None` means "let the AI guess". `source` is never accepted from the client. |
| `TaskCreateInternal` | Add `urgency_manually_set: bool = False` and `effort_level_manually_set: bool = False`, so the route can set them in the same insert. |
| `TaskUpdate` | Remove `status` (see Q1). Add a `@model_validator(mode="after")` that raises `ValueError` if `title` or `urgency` is in `model_fields_set` but is `None`. Those two columns can't be null, so an explicit `null` must be a 422, not a database error. Explicit `null` **is** allowed for `description`, `due_date` and `effort_level` (it means "clear it"). Update the docstring: this schema is now routed. |
| `TaskUpdateInternal` | Add the three new flags as `bool \| None = None`, next to `urgency_manually_set`. Update the stale comment. It stays never-instantiated, per the 2026-09-09 plain-dict convention. |
| `TaskDelete` | Keep it empty with `extra="forbid"`. Fix the stale docstring ("hard-delete only" is no longer true). |
| **New** `TaskDeletedRead` | `message: str`. Response for `DELETE /tasks/{id}`. Same shape of idea as `TelegramUnlinkRead`. |
| **New** `TaskFieldGuess` | The LLM's structured output for the guess job: `urgency: Urgency \| None = None`, `effort_level: EffortLevel \| None = None`. |

All new schemas use `X | Y` unions and `Annotated[..., Field(...)]`, per the conventions.

---

## 6. CRUD — `src/app/crud/crud_tasks.py`

No code change. FastCRUD's default `is_deleted_column="is_deleted"` / `deleted_at_column="deleted_at"`
already match the new columns, so `crud_tasks.delete()` becomes a soft delete automatically. Add a
one-line comment saying `delete()` is a soft delete, `db_delete()` is a hard delete (never called),
and that reads must pass `is_deleted=False` because FastCRUD doesn't filter it automatically.

---

## 7. Routes — `src/app/api/v1/tasks.py`

Replace the module docstring (it currently says "not a general Task CRUD API"). All routes use
`current_user: Annotated[dict, Depends(get_current_user)]` and
`db: Annotated[AsyncSession, Depends(async_get_db)]`, like the existing route. Every route sets
`response_model` and `status_code`. Route order in the file: `POST ""`, `GET ""`, `GET "/{task_id}"`,
`PATCH "/{task_id}"`, `DELETE "/{task_id}"`, then the existing `PATCH "/{task_id}/status"`.

### 7.0 Shared lookup (used by 5 routes)
One small private function in the route module:
```
async def _get_owned_task(db, task_id, current_user) -> dict:
    task = await crud_tasks.get(db=db, id=task_id, is_deleted=False)
    if not task: raise NotFoundException("Task not found.")
    if task["user_id"] != current_user["id"]: raise ForbiddenException("You do not have access to this task.")
    return task
```
It's used by get / patch / delete / status (and it keeps the "404 before 403" order the existing
route already has). This is the one place that guarantees "soft-deleted → 404 everywhere".

### 7.1 `POST /tasks` → `write_task`, `status_code=201`, `response_model=TaskRead`
1. Work out which fields to guess: `fields_to_guess = [f for f in ("urgency", "effort_level") if getattr(body, f) is None]`.
2. `crud_tasks.create(db, object=TaskCreateInternal(user_id=current_user["id"], source="manual",
   title=..., description=..., due_date=..., urgency=body.urgency or "medium",
   effort_level=body.effort_level, **manual_create_flags(body)), schema_to_select=TaskRead)`.
   `manual_create_flags` comes from `core/tasks/sticky.py` (§8.1). It sets
   `urgency_manually_set=True` if urgency was given and `effort_level_manually_set=True` if effort
   level was given.
3. If `fields_to_guess` isn't empty:
   `await queue.pool.enqueue_job("guess_task_fields", str(created["id"]), fields_to_guess)`.
4. Return the created task. The response shows the defaults right away. The AI's guess appears on
   the next read.

`source` is always `"manual"`. `TaskCreate` has no `source` field, and `extra="forbid"` rejects it
if the client sends one. Manual create does **not** run dedup, because the user asked for it
directly.

### 7.2 `GET /tasks` → `read_tasks`, `status_code=200`, `response_model=PaginatedListResponse[TaskRead]`
Query params:
- `page: Annotated[int, Query(ge=1)] = 1`
- `items_per_page: Annotated[int, Query(ge=1, le=100)] = 20`
- `status: TaskStatus | None = None`, `urgency: Urgency | None = None`, `source: TaskSource | None = None`
- `due_from: date | None = None`, `due_to: date | None = None` (both inclusive)

Steps:
1. If both dates are given and `due_from > due_to` → `BadRequestException`.
2. Build `filters = {"user_id": current_user["id"], "is_deleted": False}`, then add each filter that
   was given (`status`, `urgency`, `source`, `due_date__gte=due_from`, `due_date__lte=due_to`).
3. `crud_tasks.get_multi(db, offset=compute_offset(page, items_per_page), limit=items_per_page,
   schema_to_select=TaskRead, sort_columns=["status", "due_date", "created_at", "id"],
   sort_orders=["desc", "asc", "desc", "desc"], **filters)`.
4. `return paginated_response(crud_data=..., page=page, items_per_page=items_per_page)`.

**How the default order works with FastCRUD's plain-column sorting:**
- `status desc` puts `"open"` before `"done"`, because `"o"` sorts after `"d"`.
- `due_date asc` puts the soonest first. Postgres puts NULLs **last** on an ascending sort by
  default, so tasks with no date go last, which is exactly what we want.
- `created_at desc` is newest first. `id desc` is a final tie-breaker so pages stay stable (uuid7
  ids are time-ordered).

This depends on two facts: the alphabetical order of the only two status values, and Postgres's
default null order. A comment in the handler will say so. The live-Postgres check in §13 proves it.
If a third status is ever added, this sort must be revisited.

The other way to do it is a hand-written `select()` with `case(...)` and `.nulls_last()` plus a
separate `count()`. It's more explicit, but it abandons FastCRUD for the one list route. I recommend
the FastCRUD version above.

### 7.3 `GET /tasks/{task_id}` → `read_task`, `status_code=200`, `response_model=TaskRead`
`task = await _get_owned_task(...)`. Return it. (`response_model=TaskRead` trims it to public fields.)

### 7.4 `PATCH /tasks/{task_id}` → `patch_task`, `status_code=200`, `response_model=TaskRead`
1. `await _get_owned_task(...)`.
2. `changes = body.model_dump(exclude_unset=True)`. If it's empty, return the current task unchanged
   (no write).
3. `changes |= manual_edit_flags(changes)` (from `core/tasks/sticky.py`). This sets the flag for
   every sticky field **present in the request**, even if the value is the same as before (an
   explicit choice by the user counts as a correction). Clearing `description` or `effort_level`
   with an explicit `null` also sets the flag, so neither Notion nor the AI will fill it back in.
4. `updated = await crud_tasks.update(db, object=changes, id=task_id, is_deleted=False, schema_to_select=TaskRead)`
   (a plain dict, per the 2026-09-09 convention).
5. Return `updated`. No Notion sync (title/description are never written back to Notion — the accepted trade-off).

### 7.5 `DELETE /tasks/{task_id}` → `erase_task`, `status_code=200`, `response_model=TaskDeletedRead`
1. `await _get_owned_task(...)` (so a task that's already deleted gives 404).
2. `await crud_tasks.delete(db=db, id=task_id)`. That's the soft delete, and it commits.
3. **Nothing else:** the `notion_block_link` row stays, no Notion call, no `sync_status_to_notion`.
4. Return `{"message": "Task deleted."}`.

### 7.6 Existing `PATCH /tasks/{task_id}/status` → `patch_task_status` (kept)
Only change: use `_get_owned_task` (so it now passes `is_deleted=False`, and a deleted task gives
404). Everything else, including the unconditional `sync_status_to_notion` enqueue, stays as is.

---

## 8. Core task logic — new package `src/app/core/tasks/`

### 8.1 `core/tasks/sticky.py`
Contains the sticky-field rules, used by the routes and by Notion persistence.

```
STICKY_FLAG_BY_FIELD: dict[str, str] = {
    "title": "title_manually_set",
    "description": "description_manually_set",
    "urgency": "urgency_manually_set",
    "effort_level": "effort_level_manually_set",
}

def manual_edit_flags(changes: dict[str, Any]) -> dict[str, bool]:
    """Flag = True for every sticky field present in a user edit."""

def manual_create_flags(body: TaskCreate) -> dict[str, bool]:
    """urgency/effort_level flags = True only when the user filled them in on create."""

def drop_sticky_fields(task: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Return `changes` without any field whose sticky flag is already True on `task`."""
```
`drop_sticky_fields` is used by `persistence._update_item` (§10.2) and `dedup.fill_blanks` (§8.3),
so it isn't a one-use helper.

### 8.2 `core/tasks/dedup.py`
Near-duplicate handling for extracted tasks. It's called only from `run_memory_extraction_pipeline`.

**`load_dedup_pool(db, user_id) -> list[dict]`**
A plain SQLAlchemy `select` on `Task` (the precedent is `core/notion/jobs.py`, which already does
`select(Task.user_id)`). FastCRUD's `__or` can't combine conditions across columns. It selects `id,
title, description, due_date, effort_level, status, is_deleted, description_manually_set,
effort_level_manually_set`. The `WHERE` clause is:
```
user_id = :user_id AND (
    (is_deleted = false AND status = 'open')
 OR (is_deleted = false AND status = 'done' AND updated_at >= :cutoff)
 OR (is_deleted = true  AND deleted_at >= :cutoff)
)
ORDER BY created_at DESC
LIMIT settings.TASK_DEDUP_MAX_EXISTING_TASKS
```
with `cutoff = now(UTC) - timedelta(days=settings.TASK_DEDUP_LOOKBACK_DAYS)`. It logs a warning if
the limit is hit. (This is the one task read that includes deleted rows on purpose.)

**`merge_candidate_duplicates(candidates, embeddings) -> list[tuple[ExtractedTaskCandidate, list[float]]]`**
Removes duplicates **within one extraction result**, in memory, before anything is written.
Candidates are sorted by confidence, highest first. Each one is compared against the ones already
kept. If it's a near-duplicate (≥ threshold) of a kept one, its blanks are copied onto the kept
candidate (the same field list as below) and it's dropped. It returns the kept candidates with
their embeddings.

**`find_best_match(embedding, pool, pool_embeddings) -> tuple[dict, float] | None`**
Returns the pool task with the **highest** `cosine_similarity` if it's ≥
`TASK_DEDUP_SIMILARITY_THRESHOLD`, otherwise `None`. The highest score wins, whatever the match's
status.

### 8.3 Fill-blanks rule (inside `dedup.py`)
**`fill_blanks(db, existing: dict, candidate: ExtractedTaskCandidate) -> None`**
Only these fields are allowed, and each one only when **the existing value is empty AND its sticky
flag (if it has one) is not set**:

| Field | Filled when |
|---|---|
| `due_date` | existing is `None` and candidate has a date |
| `description` | existing is `None`/empty and `description_manually_set` is False and candidate has one |
| `effort_level` | existing is `None` and `effort_level_manually_set` is False and candidate has one |

**Never touched:** `title` (the match is already "the same task"), `urgency` (never empty, see
Q5 item 4), `status`, `source`, `memory_record_id`, `scheduled_event_id`, and any flag. The existing
task keeps its original `memory_record_id`.

If at least one field qualifies: `crud_tasks.update(db, object=fields, id=existing["id"],
commit=False)` (a plain dict, inside the pipeline's transaction). Otherwise it does no write.

**`resolve_candidates(db, user_id, candidates) -> list[ExtractedTaskCandidate]`**
The one entry point the pipeline calls. It returns only the candidates that should become **new**
tasks:
1. If `candidates` is empty, return `[]` right away (no DB read, no embedding).
2. `pool = await load_dedup_pool(...)`.
3. One batch call to `embed_texts(...)` with every candidate title **and** every pool title.
   Titles only (not title + description), because that's what the 0.85 cut-off was decided on.
4. `kept = merge_candidate_duplicates(...)`.
5. For each kept candidate, `find_best_match`:
   - no match → it goes in the "create" list;
   - match is open (`status == "open"` and not deleted) → `await fill_blanks(...)`, don't create;
   - match is done or deleted → skip, do nothing.
6. Return the "create" list.

### 8.4 `core/llm/embedding_model.py`
Add:
```
async def embed_texts(texts: list[str]) -> list[list[float]]:
    if _model is None: raise RuntimeError(...same message...)
    embeddings = await anyio.to_thread.run_sync(_model.encode, texts)
    return embeddings.tolist()  # type: ignore[no-any-return]
```
`embed_text` is left unchanged.

### 8.5 `core/llm/task_field_guess.py` (new)
Same single-shot structure as `onboarding_synthesis.py`:
- The module docstring explains the `medium` tier choice (Q4).
- `SYSTEM_PROMPT`: "You estimate missing fields for ONE task a user just typed into their personal
  assistant app. Only fill the fields you are asked for. Urgency is `low`/`medium`/`high`: use `high`
  only for explicit time pressure or importance words ('urgent', 'ASAP', 'today', a close due date),
  `low` for clearly optional/someday items, otherwise `medium`. Effort level is `deep_focus`
  (sustained concentration), `light_focus` (routine, needs some attention) or `passive` (can be done
  absent-mindedly). If you genuinely can't tell, leave the field out."
- `TASK_FIELD_GUESS_RESPONSE_FORMAT = LlmProviderResponseFormat(name="guess_task_fields", schema_=TaskFieldGuess.model_json_schema())`
- `async def call_task_field_guess_llm(title, description, due_date, fields: list[str]) -> TaskFieldGuess`
  sends `run_with_validation_retry(tier="medium", ...)`. The user message lists the title,
  description, due date (if any), and "Fields to fill: urgency, effort_level" (only the requested ones).

### 8.6 `core/tasks/jobs.py` (new) — the background guess job
```
TASK_FIELD_GUESS_MAX_TRIES = 3

async def guess_task_fields(ctx: dict[str, Any], task_id: str, fields: list[str]) -> None:
```
1. `async with local_session() as db:`
2. `task = await crud_tasks.get(db, id=UUID(task_id), is_deleted=False)`. If it's missing (deleted
   meanwhile), return.
3. `still_needed = [f for f in fields if not task[STICKY_FLAG_BY_FIELD[f]]]`. If the list is empty
   (the user already edited both), return **without** calling the LLM.
4. Call `call_task_field_guess_llm(...)` inside `try`. On any exception:
   `raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc` (same pattern as
   `core/notion/jobs.py`). After `TASK_FIELD_GUESS_MAX_TRIES` ARQ gives up. The defaults stay
   (`urgency="medium"`, `effort_level=None`), and nothing else needs to be done.
5. For each field in `still_needed` where the guess returned a value (any field the LLM returned
   that wasn't asked for is ignored), do a **conditional** write that re-checks the flag at write time:
   ```
   try:
       await crud_tasks.update(db, object={field: value}, id=task["id"], is_deleted=False,
                               **{STICKY_FLAG_BY_FIELD[field]: False})
   except NoResultFound:
       continue   # user edited it (or deleted the task) while the LLM was thinking
   ```
   Putting the flag in the `WHERE` makes the "don't overwrite a user edit" check atomic. There's no
   gap between reading the flag and writing the value. The AI guess does **not** set the flag, so a
   later Notion edit or user edit can still change it.

No `_job_id` is needed: one enqueue per create, and a retry is harmless (it only fills unflagged
fields).

---

## 9. Extraction pipeline — `src/app/core/llm/extraction.py`

Inside the existing `try:` block (same transaction, before `db.commit()`), replace the loop:
```
confident = [c for c in result.tasks if c.confidence >= settings.CONFIDENCE_THRESHOLD]
to_create = await resolve_candidates(db, user_id, confident)
for candidate in to_create:
    await crud_tasks.create(... unchanged ..., commit=False)
```
- Fill-blank updates happen inside `resolve_candidates` with `commit=False`, so everything still
  commits or rolls back together. The existing `except: rollback; raise` covers it.
- Below-threshold candidates still stay only in the record's `tasks` JSONB (unchanged).
- This covers every caller of the pipeline: Gmail, Calendar (`embed=False` only skips the *summary*
  embedding; title embeddings for dedup still run), onboarding, Telegram, and `POST /memory/ingest`.
  Notion doesn't use this pipeline, so it's untouched, as intended.
- Update the comment above the loop (the "Feature 1.11, later" wording stays true) and add one
  line about dedup.

---

## 10. Notion paths

### 10.1 `core/notion/edit_gate.py::_existing_items_for_prompt`
**Behavior: deleted tasks ARE included in the classifier prompt, exactly like live ones, with no
"deleted" marker.**
- The existing `crud.get(db=db, id=link["item_id"])` call is kept **without** `is_deleted=False`,
  on purpose. Add a comment explaining why: the classifier must still see the deleted task as
  "already handled" for this line, or it would be re-created.
- Because the link row is kept, a line whose only task was deleted still has `existing_links`, so it
  goes down the **anchored** path (never the "fresh" path). The classifier returns one outcome for the
  deleted item plus any `additional_items`. **A truly new item on the same line is still created**
  via `additional_items` → `_create_item`.
- Why no marker: telling the LLM "this was deleted" invites it to treat the item differently (e.g. to
  "re-add" it as an additional item). Giving it the same prompt as a live item gives the behavior we
  want: it recognises the text as already covered.

### 10.2 `core/notion/persistence.py::_update_item`
For `item_type == "task"`:
1. `task = await crud_tasks.get(db=db, id=action.item_id)` (all columns, no `is_deleted` filter so
   we can see the flag).
2. If `task is None` **or** `task["is_deleted"]` → return (no-op). This is the "updates aimed at a
   deleted task do nothing" rule.
3. `update_fields = drop_sticky_fields(task, update_fields)`. This skips `title`, `description`,
   `urgency`, `effort_level` wherever the matching flag is True.
4. If nothing is left → return. Otherwise update as today (`commit=False`).

The goal branch is unchanged (goals have no soft delete and no sticky flags).

`_unlink_item` on a deleted task: **it works as normal** (the link row is removed, the task stays
deleted). "No longer applies" means the line's text no longer describes that item, so nothing is
left there to re-create it from. Keeping dead links forever would only make the anchored prompt
longer. (Deletion itself never removes the link. Only the classifier retiring it does.)

`_create_item` and `_link_existing_item`: no change.

### 10.3 `core/notion/completion_sync.py`
- **`determine_desired_checked_state`** → return type becomes `bool | None`:
  - Skip any linked task whose row is missing or `is_deleted` (goals: missing only).
  - If **no live** linked items remain → return `None` ("nothing to decide, don't touch Notion").
  - Otherwise → `True` only if every live item is done (the same all-or-nothing rule as today, just
    ignoring deleted ones).
- **`sync_status_to_notion`**: if `desired_checked is None` → return without any Notion call. This
  keeps "deleting never changes Notion" true even in a race (task deleted after the job was enqueued).
- **`sync_checkbox_from_notion`** (Notion → app): skip any task that is missing or `is_deleted`. A
  checkbox tick in Notion never revives or updates a deleted task. Live siblings are still updated.

The check is `item.get("is_deleted")` on the row that's already fetched (goal rows have no such key,
so `.get` returns `None`). That's one extra condition at each site, and no new helper.

### 10.4 `core/notion/jobs.py::_active_notion_user_ids`
**No logic change.** Add a comment explaining that deleted tasks count on purpose (deleting is user
activity, and soft delete bumps `updated_at`). See Q5 item 2.

### 10.5 Complete list of task read paths after this feature

| # | Path | Sees deleted tasks? | How | Test |
|---|---|---|---|---|
| 1 | `GET /tasks` (`read_tasks`) | No | `is_deleted=False` in `get_multi` filters | `TestReadTasks::test_filters_out_deleted` |
| 2 | `GET /tasks/{id}` (`read_task`) | No → 404 | `_get_owned_task` | `TestReadTask::test_deleted_task_404` |
| 3 | `PATCH /tasks/{id}` (`patch_task`) | No → 404 | `_get_owned_task` | `TestPatchTask::test_deleted_task_404` |
| 4 | `DELETE /tasks/{id}` (`erase_task`) | No → 404 | `_get_owned_task` | `TestEraseTask::test_already_deleted_404` |
| 5 | `PATCH /tasks/{id}/status` | No → 404 | `_get_owned_task` | `TestPatchTaskStatus::test_deleted_task_404` |
| 6 | `guess_task_fields` job | No → no-op | `is_deleted=False` on read and on each conditional update | `TestGuessTaskFields::test_deleted_task_is_noop` |
| 7 | `dedup.load_dedup_pool` | **Yes, only within 60 days** (deliberate) | explicit SQL `WHERE` | `TestLoadDedupPool::*` + `TestResolveCandidates::test_deleted_match_skips` |
| 8 | `edit_gate._existing_items_for_prompt` | **Yes** (deliberate) | no filter | `TestAnchoredWithDeletedTask::*` |
| 9 | `persistence._update_item` | Reads it, then no-op | `is_deleted` check | `TestUpdateItemDeleted::test_update_on_deleted_task_is_noop` |
| 10 | `completion_sync.determine_desired_checked_state` | Ignored | `is_deleted` check | `TestDesiredCheckedState::test_deleted_task_ignored` / `test_only_deleted_returns_none` |
| 11 | `completion_sync.sync_checkbox_from_notion` | Never updated | `is_deleted` check | `TestSyncCheckboxFromNotion::test_deleted_task_not_revived` |
| 12 | `completion_sync.sync_status_to_notion` | Via #10 | `None` → no write | `TestSyncStatusToNotion::test_no_live_items_no_notion_write` |
| 13 | `notion/jobs._active_notion_user_ids` | **Yes** (deliberate, activity signal) | no filter | none (comment only, see Q5 item 2) |

Final check at build time: grep again for `crud_tasks`, `models.task`, `select(Task` and confirm
nothing new has appeared that isn't in this table.

---

## 11. Worker — `src/app/core/worker.py`
Import `guess_task_fields` and `TASK_FIELD_GUESS_MAX_TRIES` from `.tasks.jobs`, and register:
```
func(guess_task_fields, max_tries=TASK_FIELD_GUESS_MAX_TRIES),
```
The default 300s timeout is plenty for one `medium` call.

---

## 12. Tests

All async tests use `@pytest.mark.asyncio`, `mock_db`, patch-by-module-path, and `AsyncMock`, like
the existing suite. Class names follow the `TestWriteTask`/`TestReadTasks`/… convention.

### 12.1 `tests/test_tasks.py` (extend)
- **`TestWriteTask`**
  - source forced to `"manual"` (inspect the `TaskCreateInternal` passed to `crud_tasks.create`)
  - `TaskCreate(source="email", ...)` raises `ValidationError` (extra forbid)
  - urgency + effort both given → both flags True, **no** enqueue
  - both empty → `urgency="medium"`, `effort_level=None`, flags False, enqueue `("guess_task_fields", id, ["urgency", "effort_level"])`
  - only urgency given → urgency flag True, enqueue with `["effort_level"]` only
- **`TestReadTasks`**
  - default call passes `user_id`, `is_deleted=False`, the 4 sort columns/orders, and `offset/limit` from page 2 / 20 → offset 20
  - each filter (`status`, `urgency`, `source`, `due_from`→`due_date__gte`, `due_to`→`due_date__lte`) is passed through
  - `due_from > due_to` → `BadRequestException`
  - response has `data`, `total_count`, `has_more`, `page`, `items_per_page`
- **`TestReadTask`**: owned → returned; deleted (mock `get` → None, and assert it was called with `is_deleted=False`) → 404; other user's → 403
- **`TestPatchTask`**
  - editing each of `title`/`description`/`urgency`/`effort_level` sets its own flag (4 cases, parametrized) and no other flag
  - `due_date` edit sets no flag
  - explicit `description: null` → sets `description_manually_set`
  - `TaskUpdate(title=None)` explicit → `ValidationError`; `TaskUpdate(urgency=None)` explicit → `ValidationError`
  - `TaskUpdate(status="done")` → `ValidationError` (if Q1 = No)
  - empty body → no `update` call
  - deleted → 404; other user's → 403
  - no `sync_status_to_notion` enqueue
- **`TestEraseTask`**: calls `crud_tasks.delete(db=..., id=...)`, **never** `db_delete`, never touches `crud_notion_block_link`, never enqueues; already deleted → 404; other user's → 403
- **`TestPatchTaskStatus`** (existing class): update the mocks for `is_deleted=False`; add `test_deleted_task_404`

### 12.2 `tests/test_task_sticky.py` (new)
`TestManualEditFlags`, `TestManualCreateFlags`, `TestDropStickyFields` (each flag drops only its own field; no flags → unchanged).

### 12.3 `tests/test_task_dedup.py` (new) — proves (d)
Embeddings are faked with small hand-made vectors so the similarity values are known exactly (patch
`embed_texts`; `cosine_similarity` stays real).
- **`TestLoadDedupPool`**: builds the right SQL. Compile the statement and check the three `OR`
  branches, the cutoff using `TASK_DEDUP_LOOKBACK_DAYS`, and the `LIMIT`.
- **`TestFindBestMatch`**: 0.85 exactly → match; 0.849 → no match; picks the highest of several.
- **`TestResolveCandidates`**
  - no candidates → no DB call, no embedding call
  - ≥ 0.85 vs an **open** task → not created, `fill_blanks` writes only empty eligible fields
  - ≥ 0.85 vs an open task that already has `due_date`/`description`/`effort_level` → no update call at all
  - open task with `description_manually_set=True` and empty description → description **not** filled
  - ≥ 0.85 vs a **done** task (in pool, i.e. within 60 days) → skipped, no create, no update
  - ≥ 0.85 vs a **deleted** task (in pool) → skipped
  - done/deleted task **outside** 60 days → not in the pool (`load_dedup_pool` mocked to return []), so the candidate **is created**
  - < 0.85 → created
  - two near-identical candidates in one result → one created, with blanks merged from the lower-confidence one
- **`TestFillBlanks`**: urgency and title are never in the update dict.

### 12.4 `tests/test_memory_pipeline.py` / `tests/test_llm_extraction.py` (extend)
- only candidates returned by `resolve_candidates` are created
- `resolve_candidates` gets only ≥ 0.7 candidates
- an exception inside `resolve_candidates` → `db.rollback()` and re-raise, no commit

### 12.5 `tests/test_task_field_guess.py` (new) — proves (e)
- **`TestCallTaskFieldGuessLlm`**: uses tier `"medium"`; the prompt lists only the requested fields.
- **`TestGuessTaskFields`**
  - fills only fields that were requested and are still unflagged; each update is called with `is_deleted=False` and `<flag>=False` in its filters
  - field flagged since create → not in the LLM request; if all are flagged → no LLM call at all
  - `NoResultFound` on the conditional update (user edited mid-call) → skipped, other field still written
  - LLM returns a field that wasn't requested → ignored
  - LLM raises → `arq.Retry` raised, **no** `crud_tasks.update` call (defaults stay)
  - deleted task → no-op, no LLM call
- **`TestWorkerRegistration`**: `guess_task_fields` is in `WorkerSettings.functions` with `max_tries == 3`.

### 12.6 `tests/test_notion_persistence.py` (new) — proves (c)
- **`TestUpdateItemSticky`**: parametrized over the 4 flags. With the flag True, that field is left
  out of the `crud_tasks.update` object while the other fields still go through. All 4 flagged →
  no update call.
- **`TestUpdateItemDeleted`**: `is_deleted=True` → no update call; missing task → no update call.
- **`TestUpdateItemGoal`**: goal update unchanged (regression).

### 12.7 `tests/test_notion_edit_gate.py` (extend) — proves (b)
**`TestAnchoredWithDeletedTask`**
- a block whose only link points to a deleted task → goes down the **anchored** path (not fresh), and
  the deleted task's title shows up in `existing_items` passed to `reclassify_anchored_block`
- the classifier returns `unchanged` for the deleted item plus one `additional_items` entry →
  `persist_notion_block_outcome` gets exactly one `create` action (the new item) and nothing for the
  deleted one
- the classifier returns `updated` for the deleted item → end-to-end through persistence, no task update happens

### 12.8 `tests/test_notion_completion_sync.py` (extend)
- `test_deleted_task_ignored` (one deleted open + one done → `True`)
- `test_only_deleted_returns_none`
- `test_no_live_items_no_notion_write` (`sync_status_to_notion` doesn't call `update_block_checkbox` or even `get_block`)
- `test_deleted_task_not_revived` (Notion tick → only the live sibling updated)
- existing tests: keep passing (the return values for live items are unchanged)

### 12.9 `tests/test_llm_embedding_model.py` (extend)
`embed_texts` calls `encode` once with the whole list and returns a list of lists; raises
`RuntimeError` before init.

---

## 13. Verification

Run from `backend/` unless noted.

### 13.1 Migration on the real local Postgres (ports 5434/6380 via the gitignored override)
1. `docker compose up -d db redis`
2. `uv run alembic upgrade head`. Check the new revision applies on top of `65a11312d511`.
3. `psql ... -c "\d tasks"`. Check the five new columns, their types (`timestamp with time zone`,
   `boolean`), `NOT NULL`, and `DEFAULT false`.
4. `uv run alembic downgrade -1` → `\d tasks` shows the columns gone → `uv run alembic upgrade head` again.

### 13.2 Live CRUD smoke test (the kind of check that caught the 1.7 datetime bug)
A throwaway script in the scratchpad (not committed), against the real DB:
- create 4 tasks for one user: open with no due date, open due tomorrow, open due next week, done
- `crud_tasks.delete(id=...)` one of them. Check the row still exists with `is_deleted=true` and a
  tz-aware `deleted_at`, and that `updated_at` changed.
- `get_multi` with the exact route filters/sorts. Check the deleted row is missing and the order is
  open-due-tomorrow, open-due-next-week, open-no-date, done.
- run `load_dedup_pool`. Check it returns open + recent done + recent deleted, and that it excludes a
  row whose `deleted_at` was manually set to 61 days ago.
- a conditional `update(..., urgency_manually_set=False)` on a flagged row raises `NoResultFound`.
- clean up the rows.

### 13.3 Automated checks
- `uv run pytest`. Everything passes (276 existing + the new ones).
- `uv run ruff check` and `uv run ruff format --check`. Clean.
- `uv run mypy src`. Clean.

### 13.4 App boot
`uv run uvicorn ...`. `/api/v1/ready` is healthy, and `/openapi.json` lists `POST/GET /api/v1/tasks`,
`GET/PATCH/DELETE /api/v1/tasks/{task_id}` and the existing `/status` route.

### 13.5 What proves each required behavior
| Required | Proven by |
|---|---|
| (a) every read path hides deleted tasks | §10.5 table, one test per row + §13.2 live check |
| (b) deleted Notion task not re-created, new item on the same line is | §12.7 |
| (c) each sticky flag blocks Notion's overwrite | §12.6 (parametrized over all 4) |
| (d) dedup: ≥ 0.85 skip, fill blanks on open, skip done/deleted inside 60 days, create outside | §12.3 + §13.2 |
| (e) guess job fills only empty non-sticky fields, keeps defaults on failure | §12.5 |

### 13.6 Still not verified live
There's no real LLM key yet (**open item N-12**), so these have only been tested with mocks: the real
`medium`-tier guess, real extraction output flowing into dedup, and the real anchored-classifier
behavior with a deleted item (Q5 item 7). The 0.85 cut-off itself should be re-checked on real titles
once a key exists.

### 13.7 After the build
- `project-manager/erd.md`: add the 5 new `TASKS` columns.
- `phase-tracker.md`: move 1.8 to IN PROGRESS / code-complete with test counts.
- `session-notes.md`: add a new session entry.
- Commit on `feature/1.8-task-creation` only after Tola reviews.

---

## 14. Not built in 1.8 (reminder)
- Any Yes/No confirmation for unsure (< 0.7) candidates. That's Feature 1.11.
- Any way to reset a sticky flag.
- Writing app-side title/description edits back to Notion.
- Dedup for Notion-created tasks (the kept link rows already handle it) or for manual creates.
- Goals (1.9), briefing (1.10), Scouring (1.12).
- Fixing D-05 (`IntegrationConnection.connected_at` / `TelegramLink.linked_at`).
- A `completed_at` column (Q5 item 3).
