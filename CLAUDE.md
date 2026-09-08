# MyPA — Project Instructions

## Always keep the project manager office up to date

This project has a "project manager office" at [project-manager/](project-manager/) — it is the
source of truth for *where we are* and *how we're building it* (the PRDs in `dumpbox/` are the
source of truth for *what to build*). See [project-manager/README.md](project-manager/README.md)
for what each file is for.

**Update the relevant file in `project-manager/` immediately whenever any of these happen — do
not wait to be asked, and do not batch it up for "later":**

| When this happens | Update this file | With what |
|---|---|---|
| A decision is made (technical, product, or process) | [decisions-log.md](project-manager/decisions-log.md) | The decision, the rationale, and the date |
| A feature is completed | [phase-tracker.md](project-manager/phase-tracker.md) | Mark it done, note the date |
| A feature is started or its status changes | [phase-tracker.md](project-manager/phase-tracker.md) | New status |
| A feature's scope or approach is adjusted mid-build | [phase-tracker.md](project-manager/phase-tracker.md) + [decisions-log.md](project-manager/decisions-log.md) | What changed and why (this is also a decision — log it in both places) |
| Something becomes unresolved / blocked / needs a call later | [open-items.md](project-manager/open-items.md) | The item, marked Blocking or Non-Blocking |
| An open item gets resolved | [open-items.md](project-manager/open-items.md) | Move it to the item's "Resolved" sub-table with the resolution and date |
| Something is deliberately pushed out of v1/current phase | [scope-guard.md](project-manager/scope-guard.md) | What's excluded and why |
| A working session ends, or a meaningfully-sized chunk of work finishes | [session-notes.md](project-manager/session-notes.md) | What happened, state at end of session, what's next |

Rules for how to write these updates:
- Write directly into the existing file structure/tables already in each file — don't invent new
  sections unless nothing existing fits.
- Every decision and every open item gets a date.
- Never delete an entry to "clean up" — resolved items move to a "Resolved" sub-table, they
  aren't removed from the record.
- If unsure whether something rises to the level of "worth logging," prefer logging it — a
  low-value log line is cheap; a silently-lost decision or status is not.
