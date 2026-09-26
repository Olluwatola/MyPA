"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

import { PendingLabel } from "@/components/pending-label";
import { SourceBadge } from "@/components/source-badge";
import { useTimeZone } from "@/lib/auth/use-session";
import { formatDay } from "@/lib/format/date";
import type { Goal } from "@/lib/goals/labels";
import { PENDING_ID_PREFIX, type PendingKind } from "@/lib/goals/queries";
import { GoalStatusMenu } from "./goal-status-menu";
import { HorizonText } from "./horizon-text";

/**
 * One goal (design-system.md §7.3). Two separate controls — the row opens the panel, the status
 * label opens its menu — so there's never a button inside a button.
 */
export function GoalRow({ goal, pending, onOpen }: { goal: Goal; pending?: PendingKind; onOpen: (id: string) => void }) {
  const timeZone = useTimeZone();
  const unsaved = goal.id.startsWith(PENDING_ID_PREFIX);
  const ids = useId();

  return (
    <li
      className={cn(
        "flex min-h-14 items-center gap-2 border-b border-border px-2 hover:bg-muted md:px-3",
        unsaved && "opacity-70",
      )}
    >
      {/* Named by the title; the description and details are read as its description. */}
      <button
        type="button"
        disabled={unsaved}
        onClick={() => onOpen(goal.id)}
        aria-labelledby={`${ids}-title`}
        aria-describedby={`${ids}-description ${ids}-meta`}
        className="flex min-w-0 flex-1 flex-col gap-1 py-2.5 text-left md:flex-row md:items-center md:gap-4"
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span id={`${ids}-title`} className="truncate text-sm font-medium text-ink">
            {goal.title}
          </span>
          {goal.description && (
            <span id={`${ids}-description`} className="hidden truncate text-sm text-ink-2 min-[400px]:block">
              {goal.description}
            </span>
          )}
        </span>
        <span
          id={`${ids}-meta`}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2 md:shrink-0 md:text-sm"
        >
          {goal.target_date && <span className="tabular-nums">{formatDay(goal.target_date, timeZone)}</span>}
          <span>
            <HorizonText goal={goal} />
          </span>
          <SourceBadge source={goal.source} />
          {pending && <PendingLabel kind={pending} />}
        </span>
      </button>
      <GoalStatusMenu goal={goal} disabled={unsaved} />
    </li>
  );
}
