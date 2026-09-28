"use client";

import { Checkbox } from "@/components/ui/checkbox";
import type { Task } from "@/lib/tasks/labels";
import { PENDING_ID_PREFIX, useSetTaskStatus } from "@/lib/tasks/queries";

/** Ticks a task done (or not done) — optimistic, with Undo (plan §1.7). */
export function DoneCheckbox({ task }: { task: Task }) {
  const setStatus = useSetTaskStatus();
  const done = task.status === "done";

  return (
    <Checkbox
      checked={done}
      disabled={task.id.startsWith(PENDING_ID_PREFIX)}
      aria-label={done ? `Mark “${task.title}” not done` : `Mark “${task.title}” done`}
      onCheckedChange={(checked) =>
        setStatus.mutate({
          id: task.id,
          status: checked ? "done" : "open",
          previous: task.status,
          startedAt: Date.now(),
        })
      }
    />
  );
}
