import type { components } from "@/lib/api/schema";
import { SOURCES, type Source } from "@/lib/sources";

export type Task = components["schemas"]["TaskRead"];
export type TaskStatus = Task["status"];
export type Urgency = Task["urgency"];
export type EffortLevel = NonNullable<Task["effort_level"]>;

export const URGENCIES: Urgency[] = ["low", "medium", "high"];
export const URGENCY_LABEL: Record<Urgency, string> = { low: "Low", medium: "Medium", high: "High" };

export const EFFORTS: EffortLevel[] = ["deep_focus", "light_focus", "passive"];
export const EFFORT_LABEL: Record<EffortLevel, string> = {
  deep_focus: "Deep focus",
  light_focus: "Light focus",
  passive: "Passive",
};

/** The list's status switch (plan §1.3). `null` = both statuses. */
export const STATUS_VIEWS = {
  open: { label: "Open", status: "open" },
  done: { label: "Done", status: "done" },
  all: { label: "All", status: null },
} as const satisfies Record<string, { label: string; status: TaskStatus | null }>;

export type StatusView = keyof typeof STATUS_VIEWS;

/** What the list and calendar ask the API for. */
export type TaskFilters = { status: StatusView; source: Source | null; urgency: Urgency | null };

/** Everything the Tasks URL holds (plan §1.8). */
export type TaskSearch = TaskFilters & {
  view: "list" | "calendar";
  cal: "month" | "week";
  /** A day inside the calendar range shown, `YYYY-MM-DD`; `null` = today. */
  date: string | null;
  /** `?task=`: `"new"`, a task id, or `null` (panel closed). */
  task: string | null;
};

function oneOf<T extends string>(value: string | null, options: readonly T[]): T | null {
  return value !== null && (options as readonly string[]).includes(value) ? (value as T) : null;
}

/** URL → typed view state; unknown values fall back to the defaults. */
export function parseTaskSearch(params: URLSearchParams): TaskSearch {
  const date = params.get("date");
  return {
    view: oneOf(params.get("view"), ["list", "calendar"] as const) ?? "list",
    status: oneOf(params.get("status"), Object.keys(STATUS_VIEWS) as StatusView[]) ?? "open",
    source: oneOf(params.get("source"), SOURCES),
    urgency: oneOf(params.get("urgency"), URGENCIES),
    cal: oneOf(params.get("cal"), ["month", "week"] as const) ?? "month",
    date: date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null,
    task: params.get("task"),
  };
}

/** Whether a task belongs in a list shown with these filters. */
export function matchesFilters(task: Task, filters: TaskFilters): boolean {
  const status = STATUS_VIEWS[filters.status].status;
  return (
    (status === null || task.status === status) &&
    (filters.source === null || task.source === filters.source) &&
    (filters.urgency === null || task.urgency === filters.urgency)
  );
}
