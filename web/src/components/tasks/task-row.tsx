"use client";

import { CornerDownRightIcon } from "lucide-react";
import { useId } from "react";

import { PendingLabel } from "@/components/pending-label";
import { SourceBadge } from "@/components/source-badge";
import { SuggestingLabel, useGuessWindow } from "@/components/suggesting";
import { useTimeZone } from "@/lib/auth/use-session";
import { formatDay, isOverdue } from "@/lib/format/date";
import type { GoalTitle } from "@/lib/goals/queries";
import type { Task } from "@/lib/tasks/labels";
import { PENDING_ID_PREFIX, type PendingKind } from "@/lib/tasks/queries";
import { cn } from "@/lib/utils";
import { DoneCheckbox } from "./done-checkbox";
import { EffortIcon, UrgencyDot } from "./task-meta";

/** Whether the AI can still fill in urgency or effort (plan §1.5); re-renders when the window ends. */
export function useTaskGuessing(task: Task) {
  const inWindow = useGuessWindow(task.created_at);
  return {
    urgency: inWindow && !task.urgency_manually_set,
    effort: inWindow && task.effort_level == null && !task.effort_level_manually_set,
  };
}

type TaskRowProps = {
  task: Task;
  goal?: GoalTitle;
  pending?: PendingKind;
  /** Ticked in a view it no longer belongs to: shown faded until it leaves (plan §1.7). */
  leaving?: boolean;
  onOpen: (id: string) => void;
};

/**
 * One task (design-system.md §7.3): the done checkbox and the row button are separate controls, so
 * there's never a button inside a button.
 */
export function TaskRow({ task, goal, pending, leaving, onOpen }: TaskRowProps) {
  const timeZone = useTimeZone();
  const ids = useId();
  const guessing = useTaskGuessing(task);
  const unsaved = task.id.startsWith(PENDING_ID_PREFIX);
  const done = task.status === "done";
  const overdue = !done && task.due_date != null && isOverdue(task.due_date, timeZone);

  return (
    <li
      className={cn(
        "flex min-h-14 items-center gap-3 border-b border-border px-2 transition-opacity duration-(--dur-overlay) hover:bg-muted md:px-3",
        (unsaved || leaving) && "opacity-60",
      )}
    >
      <DoneCheckbox task={task} />
      {/* Named by the title; the goal and details are read as its description. */}
      <button
        type="button"
        disabled={unsaved}
        onClick={() => onOpen(task.id)}
        aria-labelledby={`${ids}-title`}
        aria-describedby={`${ids}-goal ${ids}-meta`}
        className="flex min-w-0 flex-1 flex-col gap-1 py-2.5 text-left md:flex-row md:items-center md:gap-4"
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span
            id={`${ids}-title`}
            className={cn("truncate text-sm font-medium text-ink", done && "text-ink-3 line-through")}
          >
            {task.title}
          </span>
          {goal && (
            <span id={`${ids}-goal`} className="flex min-w-0 items-center gap-1 text-xs text-ink-3">
              <CornerDownRightIcon aria-hidden className="size-3 shrink-0" />
              <span className="truncate">{goal.title}</span>
            </span>
          )}
        </span>
        <span
          id={`${ids}-meta`}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2 md:shrink-0 md:text-sm"
        >
          {task.due_date && (
            <span className={cn("tabular-nums", overdue && "text-danger")}>
              {overdue ? "Overdue · " : ""}
              {formatDay(task.due_date, timeZone)}
            </span>
          )}
          <SourceBadge source={task.source} />
          {task.effort_level && <EffortIcon effort={task.effort_level} />}
          {!guessing.urgency && <UrgencyDot urgency={task.urgency} />}
          {(guessing.urgency || guessing.effort) && <SuggestingLabel />}
          {pending && <PendingLabel kind={pending} />}
        </span>
      </button>
    </li>
  );
}
