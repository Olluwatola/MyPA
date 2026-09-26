"use client";

import { CheckCircle2Icon, CircleIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useTimeZone } from "@/lib/auth/use-session";
import { formatDay } from "@/lib/format/date";
import { useLinkedTasks } from "@/lib/goals/queries";

/** Read-only list of the tasks linked to a goal (plan §1.3). Editing tasks comes with F1.5. */
export function LinkedTasks({ goalId }: { goalId: string }) {
  const tasks = useLinkedTasks(goalId);
  const timeZone = useTimeZone();

  return (
    <section aria-labelledby="linked-tasks-heading" className="flex flex-col gap-2">
      <h3 id="linked-tasks-heading" className="text-sm font-medium text-ink">
        {tasks.data ? taskCount(tasks.data.data) : "Tasks"}
      </h3>
      {tasks.isPending ? (
        <div aria-busy="true" aria-label="Loading tasks" className="flex flex-col gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : tasks.isError ? (
        <p className="text-sm text-ink-2">Couldn&apos;t load the linked tasks.</p>
      ) : tasks.data.data.length === 0 ? (
        <p className="text-sm text-ink-2">No tasks linked yet.</p>
      ) : (
        <ul className="flex flex-col">
          {tasks.data.data.map((task) => (
            <li key={task.id} className="flex min-h-9 items-center gap-2 text-sm">
              {task.status === "done" ? (
                <CheckCircle2Icon aria-label="Done" className="size-4 shrink-0 text-success" />
              ) : (
                <CircleIcon aria-label="Open" className="size-4 shrink-0 text-ink-3" />
              )}
              <span className="min-w-0 flex-1 truncate text-ink">{task.title}</span>
              {task.due_date && (
                <span className="shrink-0 text-xs text-ink-2 tabular-nums">{formatDay(task.due_date, timeZone)}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function taskCount(tasks: { status: string }[]): string {
  const done = tasks.filter((task) => task.status === "done").length;
  const noun = tasks.length === 1 ? "task" : "tasks";
  return done > 0 ? `${tasks.length} ${noun} · ${done} done` : `${tasks.length} ${noun}`;
}
