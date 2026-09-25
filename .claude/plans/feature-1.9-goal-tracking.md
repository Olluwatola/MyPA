# Feature 1.9 — Goal tracking: implementation plan

Status: **BUILT 2026-09-24** (signed off with every recommendation). Uncommitted on
`feature/1.9-goal-tracking`. Tests 485/485 (359 before + 126 new/updated), ruff clean, mypy 13
(one fewer than the D-07 baseline). Migration round-tripped and 16/16 live smoke checks passed on
the real Postgres. HTTP walkthrough of every goal route passed (D-06 fixed live). Small build
deviations are logged in `decisions-log.md` (2026-09-24): `load_open_goals` uses plain SQLAlchemy,
`fill_blanks` takes a dict, and a few shared helpers each have more than one caller.

History: Tola confirmed the recommended answer to Q1 (shared `core/items/`), Q2 (own goal
settings), Q3 (onboarding check in both places, typed goals not checked), Q4 (AI score only, 0.7),
Q5 (checkbox rules), Q8 (paused like open, dropped like done), Q9 (clear task links on goal
delete), Q10 (fix D-08 inside 1.9), Q11.2 (newest first + multi-status filter) and Q11.3 (no
horizon flag, write only if still empty). Q6 (`medium` tier) and Q11.1/.4/.5/.6 weren't asked
separately and stand as written.
Written: 2026-09-24.
Branch: `feature/1.9-goal-tracking` (already created) from `feature/1.8-task-creation@a231d87`.

---

## 0. What I checked before writing this

I re-read the real code and the installed packages instead of trusting the brief.

**Git.** `git log --oneline --graph --all` is one straight line ending at
`a231d87` (1.8, committed 2026-09-24), on top of `024e850` (1.7). The working tree was clean. I
created `feature/1.9-goal-tracking` from `a231d87`.

**Alembic tip.** I read every migration's `revision` / `down_revision`. The chain is
`ffc94ea56c76 → b1e4f2a9c7d3 → b4020f135620 → 19fcd1375166 → a1d91b329ac8 → 116b6b923450 →
d4f8b2a6c910 → 65a11312d511 → c3a7e19d52f8`. **`c3a7e19d52f8` is still the tip.**

**Installed versions:** fastcrud 0.19.2, arq 0.26.3, SQLAlchemy 2.0.41, pydantic 2.12.5,
sentence-transformers 6.0.1. (Same as 1.8.)

**Library facts this plan depends on** (read in `.venv`, not assumed):

| Question | Answer | What it means for us |
|---|---|---|
| `update()` return value | `None` unless `return_as_model=True` (with `schema_to_select`) or `return_columns` is passed. | The D-06 fix, and every new goal PATCH, passes `return_as_model=True`, same as 1.8's task routes. |
| `update()` / `delete()` when nothing matches | `validate_update_delete_operation` runs `count()` first. 0 rows → `NoResultFound`. More than 1 row without `allow_multiple=True` → `MultipleResultsFound`. | Good for "conditional" writes (the guess job). **Not** usable for "clear `goal_id` on every task linked to this goal", because 0 linked tasks is normal and must not raise. That write uses a plain SQLAlchemy `update()` (§8.4). |
| Filter operators | `__in`, `__not_in`, `__ne`, `__gte`, … all exist (`core/filtering/operators.py`). | `status__in=[...]` works for the goal list filter. |
| `delete()` | Soft delete when the model has `is_deleted` + `deleted_at` (confirmed in 1.8). Reads never filter it themselves. | Every goal read passes `is_deleted=False`, exactly like tasks. |
| `create()` | Calls `object.model_dump()` — **Python mode**, not JSON mode. | See the bug below. |
| `pydantic.json_schema.SkipJsonSchema` | Works in 2.12.5: the field is left out of `model_json_schema()` (so the LLM never sees it) but is kept by `model_dump()`. | Used for the code-set `goal_id` on extracted task candidates (§5.3). |

**Real bug found while checking (already in the code since 1.3, not caused by 1.9):**
`run_memory_extraction_pipeline` saves `result.tasks` into the record's `tasks` JSONB column.
FastCRUD dumps it in Python mode, so a task candidate with a `due_date` puts a real `date`
object into the JSON. I tested SQLAlchemy's asyncpg JSONB bind processor with exactly that:
`TypeError: Object of type date is not JSON serializable`. So **any extraction whose AI
output includes a task with a due date crashes on insert, and the whole transaction rolls back**
(no record, no tasks). No one has seen it because no real LLM run has happened yet (N-12), and
the mocked tests never go through the real JSON encoder. 1.9 would add two more fields that fail
the same way (a goal's `target_date` and a task's `goal_id` UUID). See Q10 for the fix I
recommend.

**Other things I confirmed in the code:**
- `goals.status` is a plain `String(10)` with `server_default="open"` and no CHECK constraint.
  `paused` and `dropped` fit, so **new statuses need no DB change**.
- Nothing ever reads a stored extraction record back through Pydantic. `MemoryExtractionRecordRead`
  is only used to return the record that was *just* created. So making `ExtractedGoal.confidence`
  required can't break on older rows.
- `onboarding.py` never writes `due_date`. `SuggestedGoal` has no date at all. The brief says
  onboarding is a `due_date` writer; it isn't. The only goal `due_date` writer is
  `core/notion/persistence.py::_create_item` (plus the schemas).
- `ExtractedGoal` has no date field today, so extraction can't give a goal a `target_date` yet.
- `core/notion/goal_resolution.py` is not covered by any test file today.
- `process_telegram_callback` links whatever goal id comes back in the button's callback data.
  It never checks that the goal belongs to this user or still exists. The free-text clarification
  path doesn't check that the AI's `matched_existing_goal_id` was one of the goals it was shown
  either.

---

## 1. Answers to the open questions

These are my recommendations. Tola makes the final call on each one.

### Q1. Shared or separate dedup / sticky code for tasks and goals?
**Recommendation: shared code, moved into a new `core/items/` package, with one small
"spec" per type.**

1.8's `core/tasks/dedup.py` is really a general engine: load a pool, embed titles in one batch,
merge duplicates inside one result, find the best match, fill blanks. Only a few things are
task-specific: the model and CRUD object, the fields that can be filled, the sticky flags, which
statuses count as "live" or "closed", and the three config values. A goal copy would repeat about
160 lines, and two copies drift apart. So:

- `core/items/sticky.py` holds `manual_edit_flags` / `drop_sticky_fields` (already generic
  except for the hard-coded task map) plus two maps: `TASK_STICKY_FLAGS`, `GOAL_STICKY_FLAGS`.
- `core/items/dedup.py` holds the engine, which takes a `DedupSpec` (a small frozen dataclass),
  plus `task_dedup_spec()` and `goal_dedup_spec()`.
- `core/tasks/` keeps only `jobs.py` (the task guess job). `core/goals/` holds goal-only logic.

Cost: 1.8's `test_task_dedup.py` / `test_task_sticky.py` need their import and patch paths
updated. Their assertions stay the same, and that is the proof that task behaviour didn't change.

Why not leave the code in `core/tasks/` and just add parameters? A module called
`core.tasks.dedup` that also dedups goals would be misleading to the next reader.

### Q2. Shared or separate config?
**Recommendation: separate goal settings, with the same values as tasks for now.** A new
`GoalSettings` class (§4). The decision says "same rules as tasks", so the defaults match (0.85 /
60 days). They are separate settings because goal titles are longer and more abstract than task
titles ("Grow the newsletter to 5k" vs "Send John the contract"). When real LLM output exists
(N-12), 0.85 will probably need tuning for one type but not the other. It's three extra lines.

### Q3. Where does onboarding dedup run?
**Recommendation: both places, for two different reasons.**

1. **In the synthesis job** (`run_onboarding_ingestion`, just after `call_goal_synthesis_llm`):
   drop any suggestion that matches a goal the user already has, so the checklist never shows it.
   This matters more now than before, because **the same onboarding run now auto-creates goals
   from confident emails** (item 2 of the scope). Without this step, "Q3 fundraising" could be
   auto-created from an email *and* offered again as a suggestion a few seconds later. Nothing is
   written here, only filtered.
2. **In `POST /onboarding/goals`**, re-check each *checked suggestion* just before creating it.
   Minutes can pass between synthesis and submit, and a chat or email in that window can create
   the same goal. Also, the client sends the suggestions back, so the server shouldn't trust them.
   On a match: skip, and fill blanks if the match is open, the same as the chat/email rule.

**Typed "additional goals" are not deduped**, the same as `POST /goals` and 1.8's `POST /tasks`:
the user typed it on purpose. (If Tola prefers, they can go through the same check. It's one
extra line.)

Both use the same goal pool and threshold as chat/email dedup (`goal_dedup_spec()`).

### Q4. How does the AI decide a "confident" task → goal link, and what's the threshold?
**Recommendation: the extraction LLM picks the goal and scores its own confidence in the same
call. We accept the link only if the score is ≥ `TASK_GOAL_LINK_CONFIDENCE_THRESHOLD` (default
0.7) and the number it picked is one we actually showed it. No embedding check.**

How it works:
- The prompt lists the user's OPEN goals with short numbers, not UUIDs:
  `[1] Launch ClientPal (short term)`, `[2] Run a marathon (long term)`. LLMs copy short numbers
  reliably but often garble 36-character UUIDs. Code maps the number back to the goal's id.
- Each task candidate gets two optional LLM fields: `goal_ref: int | None` and
  `goal_link_confidence: float | None`. The prompt says: set them only when the task clearly
  serves that goal, otherwise leave them empty.
- Code accepts the link only when `goal_ref` is between 1 and the number of goals shown **and**
  `goal_link_confidence >= TASK_GOAL_LINK_CONFIDENCE_THRESHOLD`. Anything else means no link.
  An unsure link is never saved and never asked about (the question is Feature 1.11).

Why not similarity (embeddings)? Cosine similarity measures "do these two texts say the same
thing". A task and the goal it serves almost never say the same thing: "Send the landing-page copy
to Sam" serves "Launch ClientPal", but the two share almost no words or meaning, so a MiniLM score
would be low (roughly 0.2–0.5). A similarity threshold would block most correct links. "Both" (LLM
AND similarity) would block them too. The LLM already reads the task in context, so it is the
right judge.

Cost: **zero extra LLM calls.** It's part of the extraction call that already runs, and adds at
most about `GOAL_CONTEXT_MAX_OPEN_GOALS` short lines to its prompt.

Why a separate setting (default 0.7, the same number as `CONFIDENCE_THRESHOLD`): it measures
something different ("is this the right goal" vs "is this a real task"), so it should be tunable on
its own once N-12's real output exists.

Where it applies: every place the AI **creates** a task — the extraction pipeline (chat, email,
calendar, onboarding) and the three Notion prompts (fresh block, anchored block's
`additional_items`, initial page extraction). **Not** on updates: the anchored "updated" outcome
never touches `goal_id`, so the AI never changes a link once a task exists. **Not** for a task
created from a Telegram clarification reply (that path is about resolving the *block*; keeping it
link-free keeps the change small).

"Only link to OPEN goals" is enforced by construction: only open goals are ever shown.

### Q5. Notion checkbox mapping for `paused` / `dropped`
**Recommendation:**

| Direction | Rule |
|---|---|
| App → Notion (`determine_desired_checked_state`) | A **dropped** goal is ignored, exactly like a deleted one (dropping is "I gave up on this", not "I finished it", and — like deleting — it should never tick anything in Notion). A **paused** goal counts as **not done**. The checkbox is ticked only when every remaining live item is `done`. No live items left → `None` → Notion is not touched. |
| Notion → App, box **ticked** (`sync_checkbox_from_notion`) | Every live linked item that isn't done becomes `done` — **including a paused goal** (ticking the box is an explicit "it's done"). A **dropped** goal is left alone (like a deleted one: never revived). |
| Notion → App, box **unticked** | Only items that are currently `done` go back to `open`. A **paused** or **dropped** goal is left as it is. Unticking a box means "not finished", not "resume this". |

The unticked rule fixes a real problem, not just a style choice. `edit_gate.process_changed_block`
runs `sync_checkbox_from_notion` **every time any `to_do` block is processed** (stage 0), even when
the checkbox didn't change: a text edit is enough. Today's rule ("set every item to match the
box") would silently flip a paused goal on an unticked line back to `open` the next time the user
fixes a typo on that line.

### Q6. LLM tier for the horizon-guess job
**Recommendation: `medium`**, the same as 1.8's `guess_task_fields`, for the same reasons: `low` is
Ollama, which isn't installed (N-11), and `high` is overkill for picking one of two words. It's a
new small module (`core/llm/goal_horizon_guess.py`) built exactly like `task_field_guess.py`. It's
not the same function, because the prompt and output schema are different, and a combined
"guess anything" function would just be a switch statement.

### Q7. Cost bounds
Every new per-call cost has a hard cap:

| Where | Extra work | Bound |
|---|---|---|
| Every extraction (chat, email, calendar, onboarding) | 1 indexed query for open goals + a few prompt lines | `GOAL_CONTEXT_MAX_OPEN_GOALS` = 30 goals (title + horizon, about 15 tokens each, so at most about 450 tokens on a `high` call). No goals → no extra lines. |
| Every chat reply | Same query + the same list in the `medium` prompt | 30 goals |
| Every Notion classification (only after all 3 gates pass) and every Notion initial extraction (once per page) | Same query + list | 30 goals |
| Goal dedup (only when ≥ 1 confident goal came from chat/email) | 1 pool query + 1 batch embed | `GOAL_DEDUP_MAX_EXISTING_GOALS` = 200 goals |
| Goal resolution (only for "insufficient context" Notion blocks) | 1 open-goals query + 1 batch embed | 30 goals |
| Onboarding synthesis filter + submit check | 1 pool query + 1 batch embed each | 200 goals, once per user |
| Task → goal link | Nothing extra | — |

As in 1.8, a capped query logs a warning when it hits its cap, so we'll know if a real user ever
gets near it.

### Q8. Should `paused` / `dropped` goals be in the dedup pool?
The decision only names "open" and "done/deleted within 60 days". **Recommendation:**
- **paused** is treated like open (always in the pool, no time limit). A paused goal is still a
  goal the user has, and a new mention shouldn't create a second copy. **But blanks are filled
  only on an `open` match**, as the rule says, so a paused match is just skipped.
- **dropped** is treated like done (in the pool for 60 days after its last update). This keeps a
  follow-up email about a just-abandoned goal from bringing it back, while a goal the user returns
  to months later can come back.

### Q9. What happens to tasks linked to a goal that gets deleted?
`ON DELETE SET NULL` only fires on a real (hard) delete, and goal deletion is soft. So without extra
work, tasks would keep pointing at a goal that every read path now says doesn't exist, and
`GET /tasks?goal_id=<deleted goal>` would still return them.
**Recommendation:** `DELETE /goals/{id}` also clears `goal_id` on every task that points at it,
in the same transaction. The tasks' `goal_id_manually_set` flags are left as they are: nothing
re-links an existing task anyway, since the AI only links at creation. Side effect: this bumps those
tasks' `updated_at`, which restarts the 60-day dedup window for any *done* task among them.
That's harmless.
The other option is to keep the dangling pointer and filter at read time. It's more code in more
places, and it's easy to forget one.

### Q10. The JSON serialization bug (§0)
**Recommendation: fix it in 1.9**, even though it's older than 1.9. 1.9 adds `target_date` (a date)
to extracted goals and `goal_id` (a UUID) to extracted tasks, both stored in the same JSONB
columns, so every confident goal with a date, and every linked task, would hit it. The core 1.9
path can't work without the fix.
Fix: in `schemas/memory_extraction_record.py`, `MemoryExtractionRecordBase` gets one
`@field_serializer("entities", "relationships", "goals", "preferences", "tasks")` that returns
`[item.model_dump(mode="json") for item in value]`. Pydantic applies it in Python-mode dumps too,
so FastCRUD's plain `model_dump()` then produces JSON-safe dicts. It's one method, in the one
schema that feeds those columns. The live-Postgres smoke test (§17.2) proves it with a real insert.
Logged as known debt D-08 and fixed here if Tola agrees. If not, it's the first thing to fix before
N-12's live run.

### Q11. Other smaller choices (recommendations, easy to flip)
1. **`PATCH /goals/{id}` does not accept `status`**, for the same reason as 1.8's Q1: status
   changes only through `/status`, the one place that enqueues Notion sync.
2. **Goal list default order: newest first** (`created_at desc, id desc`). 1.8's trick (`status
   desc` putting `open` first) doesn't work with four statuses (`paused` sorts before `open`).
   The client filters by status instead. The `status` filter accepts **several values**
   (`?status=open&status=paused`), because "open + paused" is the natural "active goals" view. It
   maps to FastCRUD's `status__in`.
3. **No `horizon_manually_set` flag.** The guess job's write is conditional on `horizon IS NULL`
   (in the `WHERE`), which already guarantees "never overwrite a value the user set meanwhile".
   Known edge: if a user explicitly *clears* a horizon, dedup's fill-blanks could later fill it in
   again from an email. That's the same accepted trade-off as tasks' `due_date` (N-27). Logged as
   the goal twin of N-27.
4. **A user may link a task to any of their own non-deleted goals, whatever its status** (for
   example, a task under a paused goal). Only the AI is restricted to open goals.
5. **Bad `goal_id` on task create/PATCH** (missing, deleted, or another user's): `BadRequestException
   ("goal_id does not match any of your goals.")`. It's the same message for all three, so it never
   tells anyone whether another user's goal exists.
6. **`GoalRead` does not show the sticky flags or soft-delete fields**, the same as `TaskRead`.

### Q12. Things in the code that contradict the brief (flagged, not papered over)
1. Onboarding never writes `due_date` (§0). Nothing to switch there.
2. The JSON bug (§0, Q10).
3. Stage-0 checkbox sync runs on every processed `to_do` block, so the unticked rule matters (Q5).
4. `goal_resolution.py`'s threshold (0.80) and margin (0.05) were chosen for summary-vs-summary
   comparisons. Now it compares a block summary to a goal's *title + description*, which are
   shorter texts, so scores will be lower on average and it will probably ask more often. That's
   the safe direction ("prefer asking"), and the brief says to keep the check as is, so I keep both
   numbers. They should be re-checked on real data (N-12).
5. `process_telegram_callback` and the free-text clarification path trust goal ids they didn't
   check (§0). Both become goal read paths under soft delete, so both get a check (§13.6).
6. **A task can't be linked to a goal created from the same message/page.** The goal list is loaded
   *before* the LLM call, so "I want to launch ClientPal; first I'll finish the landing page" creates
   the goal and the task, but the task stays unlinked. Linking to a goal created in the same result
   would need a second referencing scheme ("candidate index" vs "existing goal number"). Not built.
   Logged as a non-blocking open item.
7. Onboarding goals auto-created from emails won't appear in the onboarding checklist (they're
   filtered out as "already there", Q3). They will be on the Goals page with source `email`. That's
   correct, but it's a UX consequence the frontend wizard (F1.4) should know about. Logged.

---

## 2. Summary of the build (in order)

| Step | What | Files |
|---|---|---|
| 1 | Migration + models | `src/migrations/versions/e5d1a8c3b947_goal_tracking.py` (new), `models/goal.py`, `models/task.py` |
| 2 | Config | `core/config.py` |
| 3 | Schemas | `schemas/goal.py`, `schemas/task.py`, `schemas/memory_extraction_record.py`, `schemas/notion_classification.py` |
| 4 | CRUD | `crud/crud_goals.py` (comment only) |
| 5 | Shared item logic | `core/items/__init__.py`, `core/items/sticky.py`, `core/items/dedup.py` (new; moved from `core/tasks/`) |
| 6 | Goal logic | `core/goals/__init__.py`, `context.py`, `onboarding.py`, `jobs.py` (new); `core/llm/goal_horizon_guess.py` (new) |
| 7 | Routes | `api/v1/goals.py` (rewrite), `api/v1/tasks.py`, `api/v1/onboarding.py` |
| 8 | Extraction pipeline | `core/llm/extraction.py` |
| 9 | Chat replies | `core/llm/conversation.py` |
| 10 | Onboarding job | `core/integrations/jobs.py` |
| 11 | Notion + Telegram | `core/notion/{persistence,edit_gate,completion_sync,goal_resolution,clarification,initial_extraction,jobs}.py`, `core/llm/{notion_classification,notion_initial_extraction}.py`, `core/telegram/jobs.py` |
| 12 | Worker | `core/worker.py` |
| 13 | Tests | §16 |
| 14 | Verify + update `project-manager/` + `erd.md` | §17 |

---

## 3. Migration + models

### 3.1 New migration: `e5d1a8c3b947_goal_tracking.py`
(The id is only a suggestion. Any fresh 12-hex id works, as long as `down_revision` is right.)
`revision = "e5d1a8c3b947"`, `down_revision = "c3a7e19d52f8"`. Hand-written, like every other one.
One migration for both tables, which matches the one-migration-per-slice precedent.

`upgrade()`:

| Table | Change | Detail |
|---|---|---|
| `goals` | add `deleted_at` | `sa.DateTime(timezone=True)`, nullable |
| `goals` | add `is_deleted` | `sa.Boolean()`, NOT NULL, `server_default=sa.text("false")` |
| `goals` | add `title_manually_set` | Boolean, NOT NULL, `server_default=false` |
| `goals` | add `description_manually_set` | Boolean, NOT NULL, `server_default=false` |
| `goals` | **drop** `due_date` | — |
| `tasks` | add `goal_id` | `postgresql.UUID(as_uuid=True)`, nullable |
| `tasks` | FK `fk_tasks_goal_id_goals` | `tasks.goal_id → goals.id`, `ondelete="SET NULL"` |
| `tasks` | index `ix_tasks_goal_id` | on `goal_id` (the `GET /tasks?goal_id=` filter and the clear-on-delete write both use it) |
| `tasks` | add `goal_id_manually_set` | Boolean, NOT NULL, `server_default=false` |

No change for the new statuses (plain `String(10)`, no constraint, §0).

`downgrade()` reverses everything in reverse order. It re-adds `goals.due_date` as a nullable
`sa.Date()`. The old values are gone, which is fine because no real user data exists (the reason
given in the 2026-09-24 decision).

### 3.2 `models/goal.py`
- `class Goal(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):`, reusing the mixin like 1.8.
- Remove `due_date`. Status comment becomes `# open | paused | done | dropped`.
- Add `title_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)` and
  `description_manually_set` the same way.
- Rewrite the docstring: sticky flags (what they block), soft delete (every read passes
  `is_deleted=False` except the named deliberate exceptions, §15), and the four statuses.

### 3.3 `models/task.py`
- `goal_id: Mapped[uuid_pkg.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("goals.id",
  ondelete="SET NULL"), nullable=True, default=None, index=True)`
- `goal_id_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)`
- Docstring: five sticky flags now. `goal_id` is one optional pointer, **not** a graph (PRD §3,
  "LLM-inferred, not graph"). No `relationship()`, per the global convention.

---

## 4. Config — `core/config.py`

A new mixin, added to `Settings(...)` next to `TaskSettings`:

```
class GoalSettings(BaseSettings):
    # Near-duplicate skip for goals auto-created from chat/email and for onboarding
    # suggestions (Notion dedups via notion_block_link). Same values as tasks today, kept
    # separate so each can be tuned on real data. Decided 2026-09-24.
    GOAL_DEDUP_SIMILARITY_THRESHOLD: float = 0.85
    GOAL_DEDUP_LOOKBACK_DAYS: int = 60
    GOAL_DEDUP_MAX_EXISTING_GOALS: int = 200
    # Cap on the open goals shown to any LLM prompt (extraction, Notion, chat) and compared
    # by goal resolution — newest first.
    GOAL_CONTEXT_MAX_OPEN_GOALS: int = 30
    # Minimum LLM-reported confidence to accept an AI task -> goal link.
    TASK_GOAL_LINK_CONFIDENCE_THRESHOLD: float = 0.7
```

`GOAL_HORIZON_GUESS_MAX_TRIES = 3` stays a module constant in `core/goals/jobs.py`, the same as
`TASK_FIELD_GUESS_MAX_TRIES`.

---

## 5. Schemas

### 5.1 `schemas/goal.py`
| Schema | Change |
|---|---|
| `GoalStatus` | `Literal["open", "paused", "done", "dropped"]` |
| `GoalBase` | Remove `due_date`. Keeps `title`, `description`, `horizon`, `target_date`. |
| `Goal` (internal) | Also inherit `PersistentDeletion`. Add `title_manually_set: bool = False`, `description_manually_set: bool = False`. |
| `GoalRead` | Remove `due_date`. Nothing else (flags and deletion fields stay internal). |
| `GoalCreate` | Keeps inheriting `GoalBase` (its `horizon: ... = None` already means "left empty — let the AI guess"). Docstring updated: routed now, `source` is always `"manual"`. `extra="forbid"`. |
| `GoalCreateInternal` | No change (inherits the `due_date` removal). |
| `GoalUpdate` | Fields `title`, `description`, `horizon`, `target_date`. **`status` removed** (Q11.1). Add a `@model_validator(mode="after")` rejecting an explicit `null` for `title` (the only non-nullable one), copying `TaskUpdate`. `null` is allowed for the other three (means "clear it"). |
| `GoalUpdateInternal` | Add `title_manually_set` / `description_manually_set` as `bool \| None = None`. Never instantiated (plain-dict convention); comment copied from `TaskUpdateInternal`. |
| `GoalDelete` | Fix the docstring (it now soft-deletes). |
| **New** `GoalDeletedRead` | `message: str`. |
| **New** `GoalHorizonGuess` | `horizon: GoalHorizon \| None = None` — the guess LLM's output. |
| `SuggestedGoal` / `GoalSynthesisResult` | No change. |

`GoalStatusUpdate` stays in the route module, as the task twin does.

### 5.2 `schemas/task.py`
| Schema | Change |
|---|---|
| `Task` (internal) | Add `goal_id: uuid_pkg.UUID \| None = None`, `goal_id_manually_set: bool = False`. |
| `TaskRead` | Add `goal_id: uuid_pkg.UUID \| None = None`. |
| `TaskCreate` | Add `goal_id: uuid_pkg.UUID \| None = None`. |
| `TaskCreateInternal` | Add `goal_id: uuid_pkg.UUID \| None = None`, `goal_id_manually_set: bool = False`. |
| `TaskUpdate` | Add `goal_id: uuid_pkg.UUID \| None = None`. Explicit `null` is allowed (it means "unlink"). Docstring mentions it. |
| `TaskUpdateInternal` | Add `goal_id_manually_set: bool \| None = None`. |

### 5.3 `schemas/memory_extraction_record.py`
- `ExtractedGoal`: add `target_date: date | None = None` and
  `confidence: Annotated[float, Field(ge=0.0, le=1.0)]` (required, same as tasks; safe per §0).
  Replace the stale docstring: goals at or above `CONFIDENCE_THRESHOLD` from conversation/email
  become real `Goal` rows (not calendar); the rest stay only in the JSONB until 1.11.
- `ExtractedTaskCandidate`: add
  - `goal_ref: int | None = None`: the LLM's pick from the numbered open-goal list
  - `goal_link_confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None`
  - `goal_id: SkipJsonSchema[uuid_pkg.UUID | None] = None`: **set by code, never by the LLM**
    (hidden from the tool schema). It's filled in from `goal_ref` right after the call (§10). This
    means dedup's fill-blanks and the task create both read the same field, and the stored record
    shows which link was made.
- `MemoryExtractionRecordBase`: the JSON-mode `@field_serializer` from Q10.

### 5.4 `schemas/notion_classification.py`
- `NotionExtractedItem`: add `goal_ref: int | None = None` and
  `goal_link_confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None` (tasks only; the
  prompt says so). `due_date` stays one field: for a goal it means its target date (mapped in
  `_create_item`, §13.1). One date field in the LLM schema is less confusing for the model than two.

---

## 6. CRUD — `crud/crud_goals.py`

No code change. Add the same 3-line comment 1.8 put on `crud_tasks.py`: `delete()` is a soft delete,
`db_delete()` is never called, and reads must pass `is_deleted=False`.

---

## 7. Shared item logic — new package `core/items/`

### 7.1 `core/items/sticky.py` (moved from `core/tasks/sticky.py`)
```
TASK_STICKY_FLAGS = {"title": ..., "description": ..., "urgency": ..., "effort_level": ...,
                     "goal_id": "goal_id_manually_set"}
GOAL_STICKY_FLAGS = {"title": "title_manually_set", "description": "description_manually_set"}

def manual_edit_flags(changes: dict[str, Any], sticky_flags: dict[str, str]) -> dict[str, bool]
def drop_sticky_fields(item: dict[str, Any], changes: dict[str, Any], sticky_flags: dict[str, str]) -> dict[str, Any]
```
Same bodies as today, with the map passed in. Adding `goal_id` to the task map means
`PATCH /tasks/{id}` sets `goal_id_manually_set` automatically when `goal_id` is in the body
(including `null`), with no extra route code. `core/tasks/sticky.py` is deleted, and
`core/tasks/jobs.py` imports `TASK_STICKY_FLAGS` from the new place.

### 7.2 `core/items/dedup.py` (moved from `core/tasks/dedup.py`, generalised)
```
@dataclass(frozen=True)
class DedupSpec:
    model: type[Task] | type[Goal]
    crud: Any                        # crud_tasks / crud_goals
    fillable_fields: tuple[str, ...]
    sticky_flags: dict[str, str]
    live_statuses: tuple[str, ...]   # always in the pool
    closed_statuses: tuple[str, ...] # in the pool if updated within the lookback
    similarity_threshold: float
    lookback_days: int
    max_existing: int
    label: str                       # "task" / "goal", for log lines

def task_dedup_spec() -> DedupSpec   # fillable ("due_date","description","effort_level","goal_id"),
                                     # live ("open",), closed ("done",), TASK_* settings
def goal_dedup_spec() -> DedupSpec   # fillable ("description","horizon","target_date"),
                                     # live ("open","paused"), closed ("done","dropped"), GOAL_* settings
```
The spec is built by a function, not a module constant, so settings are read at call time. That
keeps the existing tests' `patch(settings...)` style working.

Functions (same logic as today, parameterised by `spec`):
- `load_dedup_pool(db, spec, user_id)`: selects `id, title, status, is_deleted`, plus each
  fillable field and each fillable field's sticky flag. `WHERE user_id AND ((not deleted AND
  status IN live) OR (not deleted AND status IN closed AND updated_at >= cutoff) OR (deleted AND
  deleted_at >= cutoff))`, newest first, `LIMIT spec.max_existing`, with the cap warning.
- `merge_candidate_duplicates(candidates, embeddings, spec)`
- `find_best_match(embedding, pool, pool_embeddings, threshold)`
- `fill_blanks(db, spec, existing, candidate_fields: dict)`: fills only on the fields listed in
  the spec and never a sticky one. `commit=False`, updates `existing` in place (unchanged behaviour).
- `resolve_candidates(db, spec, user_id, candidates)`: the entry point. Blanks are filled only
  when the match's `status == "open"` and it isn't deleted. Every other match is skipped.

**New for tasks:** `goal_id` becomes fillable. If an email mentions an open task that has no goal
yet, and the AI is confident which goal it serves, the existing task gets the link, unless the
user set or cleared `goal_id` by hand (flag). This follows directly from "fill empty fields
only"; it doesn't need a separate rule.

Candidates are anything with `.title`, `.confidence` and `.model_dump()` (`ExtractedTaskCandidate`,
`ExtractedGoal`), typed as a small `Protocol` so mypy is happy.

The embedding helper `embed_texts` and `cosine_similarity` are unchanged.

---

## 8. Goal logic — new package `core/goals/`

### 8.1 `core/goals/context.py`: the shared "open goals" loader
```
async def load_open_goals(db, user_id) -> list[dict[str, Any]]
```
`crud_goals.get_multi(user_id=..., status="open", is_deleted=False, sort_columns="created_at",
sort_orders="desc", limit=settings.GOAL_CONTEXT_MAX_OPEN_GOALS, return_total_count=False)`, selecting
`id, title, description, horizon`. Paused, dropped, done and deleted goals are excluded here, and
that is the single place that rule lives for **chat context, AI linking and goal resolution**. It
logs a warning when the cap is hit.

```
def format_goals_for_prompt(goals) -> str
```
Returns `"[1] Launch ClientPal (short term)\n[2] ..."` (the horizon is left out when empty), or
`""` for no goals.

```
def resolve_goal_link(goal_ref: int | None, goal_link_confidence: float | None, goals) -> uuid | None
```
Returns `goals[goal_ref - 1]["id"]` only if `goal_ref` is in range **and** the confidence is
≥ `TASK_GOAL_LINK_CONFIDENCE_THRESHOLD`; otherwise `None`. Used by extraction and by the three
Notion create paths, so there's one rule for "confident".

These three are used by several callers (extraction, conversation, 3 Notion paths,
goal resolution), so they aren't one-use helpers.

### 8.2 Goal resolution rewrite: `core/notion/goal_resolution.py::resolve_against_existing_goals`
Same signature and same return contract. New body:
1. `goals = await load_open_goals(db, user_id)`. If empty, return `None`.
2. One `embed_texts([block_summary] + [f"{g['title']}. {g['description'] or ''}" for g in goals])`.
3. Score each goal with `cosine_similarity`. Keep the existing absolute threshold
   (`NOTION_GOAL_RESOLUTION_SIMILARITY_THRESHOLD`) **and** the margin over the runner-up
   (`NOTION_GOAL_RESOLUTION_MARGIN`), unchanged.

It no longer uses `search_similar_memories` or `crud_embeddings`, so **manual, onboarding, email
and chat goals are all visible now** (the 1.7 gap), and paused/dropped/deleted ones are not.
Module docstring updated (still "fixed code, not a model-callable tool").

### 8.3 `core/goals/onboarding.py`
```
async def drop_existing_goal_suggestions(db, user_id, suggestions: list[SuggestedGoal]) -> list[SuggestedGoal]
```
Loads the goal pool, embeds all titles in one batch, and drops each suggestion whose best match
clears the threshold (any status in the pool). No writes. Used by the onboarding job (Q3.1).

```
async def resolve_checked_suggestions(db, user_id, suggestions) -> list[SuggestedGoal]
```
Same comparison, but on an **open** match it calls `fill_blanks(db, goal_dedup_spec(), ...)`
(`commit=False`). Returns only the suggestions to create. Used by `POST /onboarding/goals` (Q3.2).

Both are built on `load_dedup_pool` / `find_best_match` / `fill_blanks` from `core/items/dedup.py`.
They don't use `resolve_candidates`, because `SuggestedGoal` has no `confidence` to sort by.

### 8.4 Clearing task links on goal delete (inline in the route, no new module)
Clearing tasks' `goal_id` on goal delete (Q9) is a single statement used only by `erase_goal`, so
it stays in the route, as a plain SQLAlchemy
`update(Task).where(Task.goal_id == goal_id).values(goal_id=None)` executed on `db` (not FastCRUD,
which raises when 0 rows match, §0). This follows the "no one-use helpers" rule.

### 8.5 `core/llm/goal_horizon_guess.py` (new)
A copy of `task_field_guess.py`'s structure:
- Docstring explains the `medium` tier (Q6).
- `SYSTEM_PROMPT`: "You estimate whether ONE goal a user just typed into their personal assistant
  app is short_term (roughly within the next few months, or a concrete near deliverable) or
  long_term (ongoing, or a year or more away). If you genuinely can't tell, leave horizon out."
- `GOAL_HORIZON_GUESS_RESPONSE_FORMAT`, from `GoalHorizonGuess.model_json_schema()`.
- `async def call_goal_horizon_guess_llm(title, description, target_date) -> GoalHorizonGuess`, via
  `run_with_validation_retry(tier="medium", ...)`.

### 8.6 `core/goals/jobs.py` (new): the background horizon guess
```
GOAL_HORIZON_GUESS_MAX_TRIES = 3

async def guess_goal_horizon(ctx: dict[str, Any], goal_id: str) -> None:
```
1. `goal = await crud_goals.get(db, id=UUID(goal_id), is_deleted=False)`. If missing (deleted
   meanwhile), return.
2. If `goal["horizon"]` is already set (the user set it meanwhile), return **without** calling the LLM.
3. LLM call inside `try`. On any exception, `raise Retry(defer=_retry_delay_seconds(job_try)) from
   exc`, the same as `guess_task_fields`. After 3 tries ARQ gives up and horizon stays empty.
4. If the guess is `None`, return. Otherwise make a conditional write:
   `crud_goals.update(db, object={"horizon": guess.horizon}, id=goal["id"], is_deleted=False, horizon=None)`,
   catching `NoResultFound` (the user set it, or deleted the goal, while the LLM was thinking). The
   condition is in the `WHERE`, so there's no gap between checking and writing.

---

## 9. Routes

### 9.1 `api/v1/goals.py` (rewrite; mirrors `api/v1/tasks.py`)
New module docstring (like the tasks one). The routes, in this order:

**`_get_owned_goal(db, goal_id, current_user)`**: `crud_goals.get(id=..., is_deleted=False)`,
404 before 403. Used by every route below except the create and list routes.

| Route | Handler | Details |
|---|---|---|
| `POST ""` → 201, `GoalRead` | `write_goal` | `crud_goals.create(GoalCreateInternal(user_id, source="manual", title, description, horizon, target_date), schema_to_select=GoalRead)`. If `body.horizon is None`, `enqueue_job("guess_goal_horizon", str(created["id"]))`. No dedup (the user asked for it directly). |
| `GET ""` → 200, `PaginatedListResponse[GoalRead]` | `read_goals` | Query: `page`, `items_per_page` (1–100, default 20), `status: Annotated[list[GoalStatus] \| None, Query()] = None` → `status__in`, `horizon: GoalHorizon \| None`, `source: GoalSource \| None`. Filters always include `user_id` and `is_deleted=False`. Sort `["created_at", "id"]` / `["desc", "desc"]` (Q11.2). `paginated_response(...)`. |
| `GET "/{goal_id}"` → 200, `GoalRead` | `read_goal` | `_get_owned_goal`. |
| `PATCH "/{goal_id}"` → 200, `GoalRead` | `patch_goal` | `changes = body.model_dump(exclude_unset=True)`. If empty, return the current goal. Otherwise `changes |= manual_edit_flags(changes, GOAL_STICKY_FLAGS)`, then `crud_goals.update(..., id, is_deleted=False, schema_to_select=GoalRead, return_as_model=True)`. No Notion write. |
| `DELETE "/{goal_id}"` → 200, `GoalDeletedRead` | `erase_goal` | `_get_owned_goal`, then the plain `update(Task)...values(goal_id=None)` (Q9, no commit yet), then `crud_goals.delete(db, id=goal_id)` (soft delete; its commit also commits the task update, same session). The link row is kept, Notion isn't touched, no sync is enqueued. `{"message": "Goal deleted."}`. |
| `PATCH "/{goal_id}/status"` → 200, `GoalRead` | `patch_goal_status` | **The D-06 fix**: uses `_get_owned_goal` (so a deleted goal gives 404) and passes `return_as_model=True`. It still enqueues `sync_status_to_notion` every time. |

### 9.2 `api/v1/tasks.py`
- A private `_check_linkable_goal(db, goal_id, current_user)`:
  `crud_goals.get(db, id=goal_id, user_id=current_user["id"], is_deleted=False)`. If missing,
  `BadRequestException("goal_id does not match any of your goals.")` (Q11.5).
- `write_task`: if `body.goal_id`, check it. `TaskCreateInternal(..., goal_id=body.goal_id,
  goal_id_manually_set=body.goal_id is not None)`. A user who fills in the goal has made a manual
  choice; an empty one is just empty (the AI never links manual tasks at create).
- `read_tasks`: new query param `goal_id: uuid_pkg.UUID | None = None` → `filters["goal_id"]`. No
  ownership check is needed: the `user_id` filter already limits results to the caller's tasks.
- `patch_task`: if `"goal_id" in changes and changes["goal_id"] is not None`, check it. The sticky
  flag comes from `manual_edit_flags(changes, TASK_STICKY_FLAGS)` (§7.1), so `goal_id: null` both
  unlinks and freezes it.
- Imports switch to `core.items.sticky`.

### 9.3 `api/v1/onboarding.py::submit_onboarding_goals`
- `to_create = await resolve_checked_suggestions(db, current_user["id"], payload.checked_suggestions)`
  runs inside the existing `try` (its fill-blank writes are `commit=False`, so they commit or roll
  back with everything else).
- Create only `to_create` (source `"conversation"`, unchanged) plus every `additional_goals` item
  (source `"manual"`, unchanged, not deduped).
- The response stays `list[GoalRead]` of **newly created** goals. A skipped duplicate isn't in it
  (the user already has it on the Goals page). Docstring says so.

---

## 10. Extraction pipeline — `core/llm/extraction.py`

`call_extraction_llm(content, open_goals)`:
- The system prompt gets three additions: (a) goals: "score each goal's confidence honestly —
  reserve ≥ 0.7 for a clearly stated, lasting aim the user holds, not a passing remark; put a real
  date in target_date only if one is stated"; (b) linking: "if the user's open goals are listed,
  set a task's goal_ref to the number of the goal it clearly serves and goal_link_confidence
  honestly; leave both empty if unsure. Never link to anything not in the list"; (c) "don't
  re-extract a goal that is already in the open-goals list".
- The user message becomes the content, plus, only when `open_goals` isn't empty,
  `"\n\nThe user's open goals:\n" + format_goals_for_prompt(open_goals)`.

`run_memory_extraction_pipeline`:
1. `open_goals = await load_open_goals(db, user_id)` **before** the LLM call (needed for the
   prompt). This is a read only, so it sits before the `try`.
2. `result = await call_extraction_llm(content, open_goals)`.
3. For each task candidate: `candidate.goal_id = resolve_goal_link(candidate.goal_ref,
   candidate.goal_link_confidence, open_goals)`. This runs before the record is created, so the
   JSONB shows the accepted link.
4. Inside the existing `try` / one transaction:
   - record + embedding (unchanged; the Q10 serializer makes the JSONB write safe)
   - **goals**, only when `source_type in GOAL_SOURCE_TYPES` (a module constant,
     `("conversation", "email")`):
     `confident_goals = [g for g in result.goals if g.confidence >= settings.CONFIDENCE_THRESHOLD]`,
     then `for g in await resolve_candidates(db, goal_dedup_spec(), user_id, confident_goals):
     crud_goals.create(GoalCreateInternal(user_id, title, description, horizon, target_date,
     source=source_type, memory_record_id=record["id"]), commit=False)`.
     Goals go before tasks so the order is easy to read in logs. It doesn't change linking, because
     linking only uses goals loaded in step 1.
   - **tasks**: unchanged except `resolve_candidates(db, task_dedup_spec(), ...)` and
     `goal_id=candidate.goal_id` on `TaskCreateInternal`. The AI's link does **not** set
     `goal_id_manually_set`.
5. Comment block updated: below-threshold goals stay only in the JSONB (1.11); calendar never
   creates goals; `POST /memory/ingest` with `source_type="notion"` doesn't either (Notion goals
   come only through Notion persistence).

Every pipeline caller (Gmail, Calendar, onboarding, Telegram, `POST /memory/ingest`) is covered
with no change at the call sites.

---

## 11. Chat replies — `core/llm/conversation.py::generate_conversation_reply`

After loading history and memories: `open_goals = await load_open_goals(db, user_id)`. If not
empty, add one system message after the memory block:
`"The user's open goals (use them when helping them prioritise):\n" + lines`, where each line is
`- {title} ({horizon})` (the horizon is left out when empty). There are no numbers here, because the
chat reply never refers back to a goal by number. Paused, dropped, done and deleted goals never
appear (the loader rule). The system prompt gets one sentence: "When the user asks what to focus
on, weigh their open goals."

---

## 12. Onboarding job — `core/integrations/jobs.py::run_onboarding_ingestion`

One change, after `result = await call_goal_synthesis_llm(summaries)`:
```
kept = await drop_existing_goal_suggestions(db, user_uuid, result.suggested_goals)
suggested_goals = [g.model_dump(mode="json") for g in kept]
```
It's inside the existing `try`, so a failure there takes the job's existing retry path. Docstring
note: confident email goals are auto-created earlier in the same run (through the pipeline), and
this filter is what stops them being suggested again.

---

## 13. Notion + Telegram

### 13.1 `core/notion/persistence.py`
- `NotionPersistenceAction` gains `goal_id: uuid_pkg.UUID | None = None` (for a task create: the
  accepted AI link).
- `_create_item`:
  - task: add `goal_id=action.goal_id`.
  - goal: **`due_date` → `target_date=action.due_date`**, with a comment that the Notion LLM schema
    has one date field and a goal's date is its target date (decision 6).
  - Notion still dedups by link row only. No similarity dedup here (unchanged decision).
- `_update_item` goal branch, now mirroring the task branch:
  `goal = await crud_goals.get(db, id=action.item_id)` (no `is_deleted` filter, on purpose); if it's
  missing or deleted, return (no-op); `goal_fields = drop_sticky_fields(goal, {title, description
  subset}, GOAL_STICKY_FLAGS)`; update only if anything is left. The task branch switches to
  `drop_sticky_fields(task, fields, TASK_STICKY_FLAGS)`. `goal_id` is never in `update_fields`, so
  Notion updates never touch a link.
- `_link_existing_item`: no change (callers now pass only checked goal ids, §8.2 / §13.6).

### 13.2 `core/notion/edit_gate.py`
- `_existing_items_for_prompt`: **no logic change**. It already reads without an `is_deleted`
  filter, so a soft-deleted *goal* is now treated exactly like a deleted task: still shown, so it
  stays "already handled". Docstring updated to say "tasks and goals". This is the goal half of
  required proof (b).
- `_item_to_create_action(item, open_goals)`: new param. It sets
  `goal_id=resolve_goal_link(item.goal_ref, item.goal_link_confidence, open_goals) if item.item_type
  == "task" else None`.
- `_handle_fresh_classification` / `_handle_anchored_classification`: `open_goals = await
  load_open_goals(db, user_id)` once, then passed to `classify_fresh_block` /
  `reclassify_anchored_block` and to `_item_to_create_action`. The anchored "updated" outcome is
  untouched (no linking on update, Q4).

### 13.3 `core/llm/notion_classification.py` and `core/llm/notion_initial_extraction.py`
- `classify_fresh_block(full_page_text, target_block, open_goals)`,
  `reclassify_anchored_block(..., existing_items, open_goals)`,
  `extract_chunk(full_page_text, chunk_blocks, open_goals)`: when not empty, append
  `"The user's open goals:\n" + format_goals_for_prompt(open_goals)` to the user message.
- Each system prompt gets the same two sentences: "For a TASK only, if one of the user's listed
  open goals is clearly what it serves, set goal_ref to that goal's number and goal_link_confidence
  honestly; otherwise leave both empty. For a goal, due_date means its target date."

### 13.4 `core/notion/initial_extraction.py::run_initial_extraction`
Load `open_goals` once per page (before the `asyncio.gather`), pass it to every `extract_chunk`, and
set `goal_id=resolve_goal_link(...)` for task items when building each `NotionPersistenceAction`.

### 13.5 `core/notion/completion_sync.py` (rules from Q5)
- `determine_desired_checked_state`: an item counts as live only if it exists, isn't deleted, and
  **isn't a dropped goal**. No live items → `None`. Otherwise `all(status == "done")`, so a paused
  goal counts as not done.
- `sync_checkbox_from_notion`: skip missing, deleted, and **dropped** items. If `checked`: every
  remaining item not already `done` → `done` (a paused goal included). If not `checked`: **only
  items whose status is `done`** → `open`. Paused stays paused.
- Docstring gains the mapping table from Q5. `item.get("is_deleted")` now works for goals too (the
  column exists), so the comment "goal rows have no is_deleted key" is removed.

### 13.6 Clarification (Notion "insufficient context" via Telegram)
- `core/notion/clarification.py::escalate_insufficient_context`: add `is_deleted=False` to the
  candidate goals `get_multi` (`status="open"` already excludes paused/dropped/done).
- `core/telegram/jobs.py::_resolve_pending_clarification`: add `is_deleted=False` to its
  `get_multi`. **New check:** accept `resolution.matched_existing_goal_id` only if it's one of the
  `candidate_goals` ids it was shown. Otherwise treat it as "no match" (the AI returned an id it
  wasn't given).
- `core/telegram/jobs.py::process_telegram_callback`: **new check** before linking:
  `crud_goals.get(db, id=goal_id, user_id=user_uuid, is_deleted=False)`. If it's missing, send
  "That goal is no longer available — reply with the goal's name instead." and return, leaving the
  clarification pending.

### 13.7 `core/notion/jobs.py::_active_notion_user_ids`
**No logic change.** Add to the docstring that soft-deleted *goals* also count on purpose (deleting
is activity, and soft delete bumps `updated_at`), the same reasoning 1.8 recorded for tasks.

---

## 14. Worker — `core/worker.py`
Import `guess_goal_horizon`, `GOAL_HORIZON_GUESS_MAX_TRIES` from `.goals.jobs` and register
`func(guess_goal_horizon, max_tries=GOAL_HORIZON_GUESS_MAX_TRIES)`. The default 300s timeout is plenty.
`.tasks.jobs` imports are unchanged.

---

## 15. Complete list of goal read paths after this feature

Final check at build time: grep again for `crud_goals`, `models.goal`, `select(Goal`, `Goal.` and
confirm nothing is missing from this table.

| # | Path | Sees deleted goals? | Sees paused/dropped? | How | Test |
|---|---|---|---|---|---|
| 1 | `GET /goals` | No | Yes (filterable) | `is_deleted=False` filter | `TestReadGoals::test_filters_out_deleted` |
| 2 | `GET /goals/{id}` | No → 404 | Yes | `_get_owned_goal` | `TestReadGoal::test_deleted_goal_404` |
| 3 | `PATCH /goals/{id}` | No → 404 | Yes | `_get_owned_goal` | `TestPatchGoal::test_deleted_goal_404` |
| 4 | `DELETE /goals/{id}` | No → 404 | Yes | `_get_owned_goal` | `TestEraseGoal::test_already_deleted_404` |
| 5 | `PATCH /goals/{id}/status` | No → 404 | Yes | `_get_owned_goal` | `TestPatchGoalStatus::test_deleted_goal_404` |
| 6 | Task create/PATCH `goal_id` check | No → 400 | Yes (user may link) | `is_deleted=False` + `user_id` | `TestWriteTask::test_deleted_goal_rejected`, `TestPatchTask::test_other_users_goal_rejected` |
| 7 | `guess_goal_horizon` job | No → no-op | Yes | `is_deleted=False` on read and on the conditional write | `TestGuessGoalHorizon::test_deleted_goal_is_noop` |
| 8 | `load_open_goals` (chat, extraction linking, Notion prompts, goal resolution) | No | **No** | `status="open", is_deleted=False` | `TestLoadOpenGoals::test_filters` |
| 9 | Goal dedup pool (`load_dedup_pool` with the goal spec) | **Yes, within 60 days** (deliberate) | paused always, dropped 60 days | explicit SQL | `TestLoadDedupPoolGoals::*` |
| 10 | Onboarding synthesis filter / submit check | Via #9 | Via #9 | — | `TestDropExistingGoalSuggestions`, `TestSubmitOnboardingGoals::test_existing_goal_not_created` |
| 11 | `edit_gate._existing_items_for_prompt` | **Yes** (deliberate) | Yes | no filter | `TestAnchoredWithDeletedGoal::*` |
| 12 | `persistence._update_item` (goal) | Reads it, then no-op | Yes | `is_deleted` check | `TestUpdateItemGoal::test_update_on_deleted_goal_is_noop` |
| 13 | `completion_sync.determine_desired_checked_state` | Ignored | dropped ignored, paused = not done | checks | `TestDesiredCheckedState::test_goal_*` |
| 14 | `completion_sync.sync_checkbox_from_notion` | Never updated | dropped never updated; paused → done on tick only | checks | `TestSyncCheckboxFromNotion::test_goal_*` |
| 15 | `completion_sync.sync_status_to_notion` | Via #13 | Via #13 | `None` → no write | existing + new goal cases |
| 16 | `clarification.escalate_insufficient_context` | No | No | `status="open", is_deleted=False` | `TestEscalate::test_candidate_goals_exclude_deleted` |
| 17 | `telegram._resolve_pending_clarification` | No | No | same + id-in-list check | `TestResolvePendingClarification::test_unknown_goal_id_ignored` |
| 18 | `telegram.process_telegram_callback` | No → message, stays pending | Yes (user tapped it) | ownership + `is_deleted` check | `TestProcessTelegramCallback::test_deleted_goal_not_linked` |
| 19 | `notion/jobs._active_notion_user_ids` | **Yes** (deliberate, activity) | Yes | no filter | none (comment only) |
| 20 | `GET /tasks?goal_id=` | n/a (task filter) | n/a | tasks of a deleted goal were un-linked at delete (Q9) | `TestEraseGoal::test_clears_task_links` |

---

## 16. Tests

All async tests use `@pytest.mark.asyncio`, `mock_db`, patch-by-module-path and `AsyncMock`, like the
existing suite. Class names follow `TestWriteGoal` / `TestReadGoals` / … .

### 16.1 `tests/test_goals.py` (rewrite + extend)
- **`TestWriteGoal`**: source forced to `"manual"`; `GoalCreate(source=...)` → `ValidationError`;
  horizon given → no enqueue; horizon empty → `enqueue_job("guess_goal_horizon", id)`.
- **`TestReadGoals`**: default call passes `user_id`, `is_deleted=False`, the sort, offset/limit;
  `status=["open","paused"]` → `status__in`; `horizon`, `source` passed through; response shape.
- **`TestReadGoal`**: owned → returned; deleted → 404 (asserts `is_deleted=False` was passed); other
  user's → 403.
- **`TestPatchGoal`**: editing `title` / `description` sets only its own flag (parametrized);
  `horizon` / `target_date` set no flag; explicit `description: null` sets its flag;
  `GoalUpdate(title=None)` → `ValidationError`; `GoalUpdate(status="done")` → `ValidationError`;
  empty body → no update; `return_as_model=True` asserted; deleted → 404; other user's → 403; no
  Notion enqueue.
- **`TestEraseGoal`**: calls `crud_goals.delete`, never `db_delete`; executes the task-unlink
  `update` statement on `db` (compile and check `goal_id = NULL` / `WHERE goal_id = :id`); never
  touches `crud_notion_block_link`; never enqueues; already deleted → 404.
- **`TestPatchGoalStatus`** (extend): accepts `paused` and `dropped`; **proves (i)**: asserts
  `update` was called with `return_as_model=True` and the route returns the updated goal; deleted
  → 404.

### 16.2 `tests/test_tasks.py` (extend)
- `TestWriteTask`: valid `goal_id` → saved with `goal_id_manually_set=True`; deleted / other
  user's / missing goal → `BadRequestException`; no `goal_id` → flag False.
- `TestReadTasks`: `goal_id` filter passed through.
- `TestPatchTask`: `goal_id` edit sets `goal_id_manually_set`; `goal_id: null` sets the flag and
  skips the goal check; a bad goal → 400.

### 16.3 `tests/test_items_sticky.py` (renamed from `test_task_sticky.py`) and `tests/test_items_dedup.py` (renamed from `test_task_dedup.py`)
- All existing 1.8 cases kept, run against `task_dedup_spec()` / `TASK_STICKY_FLAGS` (the
  regression proof that tasks behave exactly as before).
- New goal cases, **proving (d)**: ≥ 0.85 vs an open goal → not created, blanks filled
  (`description` / `horizon` / `target_date`, and not `description` when its flag is set); vs a
  **paused** goal → skipped, **no** fill; vs a done or dropped goal inside 60 days → skipped;
  outside 60 days (not in pool) → created; vs a deleted goal inside 60 days → skipped; < 0.85 →
  created. `load_dedup_pool` with the goal spec: compile and check `status IN ('open','paused')`,
  `status IN ('done','dropped') AND updated_at >= cutoff`, the deleted branch, and `LIMIT 200`.
- New task case: an open task with no `goal_id` gets it filled from a confident candidate; not
  when `goal_id_manually_set` is True.

### 16.4 `tests/test_memory_pipeline.py` / `tests/test_llm_extraction.py` (extend)
- **(d)** confidence gate: goals at 0.69 are not created, goals at 0.7 go to `resolve_candidates`
  with the goal spec; only its survivors are created, with `source` = the pipeline's
  `source_type` and `target_date` passed through.
- `source_type="calendar"` (and `"notion"`) → **no** goal created even at 0.95.
- **(f)** linking: `goal_ref=1, goal_link_confidence=0.8` → the task is created with goal 1's id;
  `0.69` → `goal_id=None`; `goal_ref=5` with only 2 goals shown → `None`; no open goals → the prompt
  has no goal block and `goal_id=None`; the created task never gets `goal_id_manually_set=True`.
- The prompt includes `format_goals_for_prompt(open_goals)` when goals exist.
- An exception inside goal creation → `db.rollback()` + re-raise, no commit.
- **Q10 fix:** `MemoryExtractionRecordCreate(... tasks=[candidate with due_date and goal_id],
  goals=[goal with target_date]).model_dump()` → `json.dumps(...)` succeeds (dates and UUIDs are
  strings).
- `ExtractedTaskCandidate.model_json_schema()` does **not** contain `goal_id`, but does contain
  `goal_ref`.

### 16.5 `tests/test_goal_context.py` (new) — proves (h)
- **`TestLoadOpenGoals`**: `get_multi` called with `status="open"`, `is_deleted=False`, the cap, newest
  first; warning when the cap is hit.
- **`TestFormatGoalsForPrompt`**: numbering, horizon shown or left out, empty list → `""`.
- **`TestResolveGoalLink`**: in range and ≥ threshold → id; below threshold → None; ref 0, negative
  or too big → None; `None` ref → None.

### 16.6 `tests/test_llm_conversation.py` (extend) — proves (h)
- Open goals → the goal system message is present with titles/horizons.
- `load_open_goals` returns [] → no goal message. (Paused/dropped exclusion itself is proven in
  16.5, since the loader is the only source.)

### 16.7 `tests/test_notion_goal_resolution.py` (new) — proves (g)
- A **manual** goal (no `memory_record_id`) with a close title → returned (the 1.7 gap is closed).
- Two goals within the margin → `None`; best below 0.80 → `None`; no open goals → `None`, no embed
  call.
- It never calls `search_similar_memories` (patched, asserted not awaited).
- One `embed_texts` call for summary + all goals.

### 16.8 `tests/test_notion_persistence.py` (extend) — proves (c)
- **`TestUpdateItemGoal`** (replaces the 1.8 regression case): parametrized over `title_manually_set` /
  `description_manually_set`: that field is dropped and the other still goes through; both
  flagged → no update; a deleted goal → no update; a missing goal → no update.
- **`TestCreateItem`**: a goal create writes `target_date` (from `action.due_date`) and no
  `due_date`; a task create passes `goal_id`.

### 16.9 `tests/test_notion_edit_gate.py` (extend) — proves (b) for goals and (f) for Notion
- **`TestAnchoredWithDeletedGoal`**: a block whose only link is a deleted goal → anchored path, the
  goal's title is in `existing_items`; `unchanged` + one additional item → exactly one `create`
  action, nothing for the deleted goal; `updated` on the deleted goal → no goal update end to end.
- A fresh `actionable` task item with `goal_ref=1, goal_link_confidence=0.9` → its create action
  carries goal 1's id; with `0.5` → `goal_id=None`; a goal item's `goal_ref` is ignored.
- Open goals are passed to both classify functions.

### 16.10 `tests/test_notion_completion_sync.py` (extend)
- `determine_desired_checked_state`: dropped goal + done task → `True`; only a dropped goal →
  `None`; paused goal + done task → `False`; deleted goal ignored.
- `sync_checkbox_from_notion`: tick → paused goal becomes done, dropped untouched; **untick → paused
  stays paused, dropped stays dropped, only done goes to open** (the stage-0 fix).

### 16.11 `tests/test_notion_initial_extraction.py` (extend)
`extract_chunk` gets the open goals; a confident task item's action carries the linked `goal_id`.

### 16.12 `tests/test_notion_clarification.py` / `tests/test_telegram_jobs.py` / `tests/test_telegram_webhook.py` (extend)
- Candidate goal queries include `is_deleted=False`.
- `_resolve_pending_clarification`: a `matched_existing_goal_id` not in the shown list → no link action.
- `process_telegram_callback`: a deleted or other user's goal → no `persist_notion_block_outcome`
  call, the message is sent, and the clarification is not cleared.

### 16.13 `tests/test_goal_onboarding.py` (new) + `tests/test_onboarding.py` / `tests/test_integration_jobs.py` (extend) — proves (e)
- `drop_existing_goal_suggestions`: a suggestion matching an existing goal is removed; one that
  doesn't match is kept; no writes.
- `resolve_checked_suggestions`: an open match fills blanks and isn't returned; a paused match is
  skipped with no fill.
- `submit_onboarding_goals`: a checked suggestion matching an existing goal is **not** created; a
  typed extra with the same title **is** created (not deduped); the response lists only new goals.
- `run_onboarding_ingestion`: `onboarding_suggested_goals` is saved **after** the filter
  (the filter patched to drop one; the stored list is one shorter).

### 16.14 `tests/test_goal_horizon_guess.py` (new)
- `call_goal_horizon_guess_llm` uses tier `"medium"`.
- `guess_goal_horizon`: fills an empty horizon with a conditional update (`horizon=None`,
  `is_deleted=False` in the filters); horizon already set → no LLM call; `NoResultFound` →
  swallowed; guess `None` → no update; LLM raises → `arq.Retry`, no update; deleted goal → no-op.
- **`TestWorkerRegistration`**: `guess_goal_horizon` is registered with `max_tries == 3`.

---

## 17. Verification

Run from `backend/` unless noted.

### 17.1 Migration on the real local Postgres (ports 5434/6380 via the gitignored override)
1. `docker compose up -d db redis`
2. `uv run alembic upgrade head` → `e5d1a8c3b947` applies on top of `c3a7e19d52f8`.
3. `\d goals`: `deleted_at timestamptz`, `is_deleted` / `title_manually_set` /
   `description_manually_set` `boolean NOT NULL DEFAULT false`, **no `due_date`**.
   `\d tasks`: `goal_id uuid`, FK to `goals(id)` `ON DELETE SET NULL`, `ix_tasks_goal_id`,
   `goal_id_manually_set boolean NOT NULL DEFAULT false`.
4. `uv run alembic downgrade -1` → both tables back to their 1.8 shape (`goals.due_date` back,
   nullable) → `uv run alembic upgrade head` again.

### 17.2 Live CRUD smoke test (a throwaway script in the scratchpad, not committed)
- Create 4 goals (`open` / `paused` / `done` / `dropped`) and 2 tasks linked to the open goal.
- Soft-delete the open goal through the same statements `erase_goal` runs: the row still exists with
  `is_deleted=true`, a tz-aware `deleted_at`, and both tasks now have `goal_id IS NULL`.
- Hard-delete another goal (`db_delete`) that has a linked task: that task's `goal_id` becomes NULL
  (proves the FK's `ON DELETE SET NULL`).
- `get_multi` with the route filters (`status__in=["open","paused"]`, `is_deleted=False`): the right
  rows, newest first.
- `load_dedup_pool` with the goal spec: open + paused + recent done/dropped/deleted, and **not** a
  row whose `updated_at` / `deleted_at` was set to 61 days ago.
- The guess job's conditional `update(..., horizon=None)` on a goal whose horizon is set →
  `NoResultFound`.
- **The Q10 fix:** insert a real `MemoryExtractionRecord` with a task candidate carrying a
  `due_date` + `goal_id` and a goal with a `target_date`. It succeeds, and reading the JSONB back
  shows ISO strings. (Before the fix, the same insert fails; run it once before the fix to show the
  bug is real.)
- Clean up.

### 17.3 Automated checks
- `uv run pytest`: everything passes (359 existing, some moved/renamed, plus the new ones).
- `uv run ruff check` and `uv run ruff format --check`: clean.
- `uv run mypy src`: **no new errors** over the 14-error baseline (D-07).

### 17.4 App boot + HTTP walkthrough (the check that found D-06)
`uv run uvicorn ...`, then register → login → curl every goal route:
`POST /goals` (201; with and without horizon), `GET /goals?status=open&status=paused`,
`GET /goals/{id}`, `PATCH /goals/{id}`, `PATCH /goals/{id}/status` with `paused` (**200 with the
goal's JSON**, proving (i) for real, not just mocked), `DELETE /goals/{id}` then `GET` → 404,
`POST /tasks` with a `goal_id` and `GET /tasks?goal_id=`, and `POST /tasks` with the deleted goal's
id → 400. `/openapi.json` lists all the routes.

### 17.5 What proves each required behaviour
| Required | Proven by |
|---|---|
| (a) every goal read path hides deleted goals | §15 table, one test per row + §17.2 |
| (b) a deleted Notion goal isn't re-created on a block edit | §16.9 `TestAnchoredWithDeletedGoal` |
| (c) sticky title/description block Notion's overwrite | §16.8 `TestUpdateItemGoal` |
| (d) chat/email goals confidence-gated + deduped (skip, fill blanks, 60 days) | §16.4 + §16.3 + §17.2 |
| (e) onboarding doesn't suggest or create an existing goal | §16.13 |
| (f) AI links only when confident; a user-set link never changes | §16.4 + §16.9 (confidence); §16.3 (fill-blanks respects `goal_id_manually_set`) + §16.2 (PATCH sets it) + the anchored update path never carries `goal_id` (§16.9) |
| (g) goal resolution matches a manual goal | §16.7 |
| (h) paused/dropped excluded from chat context and linking | §16.5 (the loader) + §16.6 + §16.4 (linking only from the loader's list) |
| (i) fixed status route returns 200 with the goal | §16.1 + §17.4 |

### 17.6 Still not verified live
No real LLM key yet (**N-12**). Only mocks cover these: real goal confidence scores (is 0.7 a good
bar for "passing remark" vs "real goal"?), real `goal_ref` / `goal_link_confidence` behaviour, the
horizon guess, the anchored classifier with a deleted goal (the goal twin of N-28), and goal
resolution's 0.80 / 0.05 on title-vs-summary scores (Q12.4). The 0.85 goal dedup cut-off should be
re-checked on real goal titles too.

### 17.7 After the build
- `project-manager/erd.md`: `GOALS` gains `deleted_at`, `is_deleted`, `title_manually_set`,
  `description_manually_set`, loses `due_date`, and `status` lists 4 values; `TASKS` gains `goal_id`
  (FK → GOALS, nullable) and `goal_id_manually_set`, plus the new `TASKS }o--o| GOALS` line.
- `phase-tracker.md`, `session-notes.md`, `decisions-log.md` (confirm the proposed rows), and
  `open-items.md` (close B-03, D-06, and D-08 if fixed).
- Commit on `feature/1.9-goal-tracking` only after Tola reviews.

---

## 18. Not built in 1.9 (reminder)
- Goal creation from calendar events.
- Any Yes/No confirmation for unsure goals or unsure task → goal links (1.11).
- The morning briefing or "goal falling behind pace" (1.10 / 1.11).
- A graph, or many-to-many task↔goal links. One optional `goal_id` only.
- A sticky-flag reset; writing app-side goal edits back to Notion.
- Linking a task to a goal created in the same message/page (Q12.6, logged).
- AI re-linking an existing task on a Notion "updated" outcome.
- Similarity dedup for Notion-created goals (the link row still handles it) or for manual /
  typed-onboarding goals.
- Fixes to D-05 and D-07. (D-08, the JSON bug, is the one exception, and only if Tola agrees in Q10,
  because 1.9's own path depends on it.)
