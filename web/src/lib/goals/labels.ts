import type { components } from "@/lib/api/schema";

export type Goal = components["schemas"]["GoalRead"];
export type GoalStatus = Goal["status"];
export type GoalHorizon = NonNullable<Goal["horizon"]>;

export const STATUS_LABEL: Record<GoalStatus, string> = {
  open: "Open",
  paused: "Paused",
  done: "Done",
  dropped: "Dropped",
};

export const STATUSES: GoalStatus[] = ["open", "paused", "done", "dropped"];

export const HORIZON_LABEL: Record<GoalHorizon, string> = {
  short_term: "Short-term",
  long_term: "Long-term",
};

/** The list's status switch (plan §1.2). `null` = no status filter. */
export const VIEWS = {
  active: { label: "Active", statuses: ["open", "paused"] },
  done: { label: "Done", statuses: ["done"] },
  dropped: { label: "Dropped", statuses: ["dropped"] },
  all: { label: "All", statuses: null },
} as const satisfies Record<string, { label: string; statuses: GoalStatus[] | null }>;

export type GoalView = keyof typeof VIEWS;

export function parseView(value: string | null): GoalView {
  return value !== null && value in VIEWS ? (value as GoalView) : "active";
}

export function viewIncludes(view: GoalView, status: GoalStatus): boolean {
  const statuses: readonly GoalStatus[] | null = VIEWS[view].statuses;
  return statuses === null || statuses.includes(status);
}
