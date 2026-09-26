"use client";

import { ChevronDownIcon } from "lucide-react";
import { cn } from "@/lib/utils";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { STATUS_LABEL, STATUSES, type Goal, type GoalStatus } from "@/lib/goals/labels";
import { useSetGoalStatus } from "@/lib/goals/queries";

/** Status label that opens a menu to change it (plan §1.7). Paused stands out; the rest are quiet. */
export function GoalStatusMenu({ goal, disabled = false }: { goal: Goal; disabled?: boolean }) {
  const setStatus = useSetGoalStatus();
  const label = STATUS_LABEL[goal.status];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={disabled}
        aria-label={`Status: ${label}. Change status`}
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1 rounded-full px-2.5 text-xs font-medium whitespace-nowrap hover:bg-muted disabled:opacity-50 pointer-coarse:h-11",
          goal.status === "paused" ? "border border-warning text-warning" : "text-ink-2",
        )}
      >
        {label}
        <ChevronDownIcon aria-hidden className="size-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup
          value={goal.status}
          onValueChange={(value) => {
            const status = value as GoalStatus;
            if (status !== goal.status) setStatus.mutate({ id: goal.id, status, previous: goal.status });
          }}
        >
          {STATUSES.map((status) => (
            <DropdownMenuRadioItem key={status} value={status}>
              {STATUS_LABEL[status]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
