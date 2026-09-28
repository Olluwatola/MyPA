import { addDays } from "@/lib/format/date";
import type { Task } from "./labels";

// Plan §1.4: headings in the Open view. "Next 7 days" rather than "This week" so the heading
// doesn't depend on which day a week starts on.
export type DueGroup = "overdue" | "today" | "tomorrow" | "next7" | "later" | "none";

export const DUE_GROUP_LABEL: Record<DueGroup, string> = {
  overdue: "Overdue",
  today: "Today",
  tomorrow: "Tomorrow",
  next7: "Next 7 days",
  later: "Later",
  none: "No date",
};

/** `today` is `YYYY-MM-DD` in the user's timezone. */
export function dueGroup(dueDate: string | null | undefined, today: string): DueGroup {
  if (!dueDate) return "none";
  if (dueDate < today) return "overdue";
  if (dueDate === today) return "today";
  if (dueDate === addDays(today, 1)) return "tomorrow";
  if (dueDate <= addDays(today, 7)) return "next7";
  return "later";
}

/**
 * Groups an already-sorted list (the backend sorts open tasks by due date, no date last), keeping
 * the order, so the headings never jump around as more pages load.
 */
export function groupTasks(tasks: Task[], today: string): { group: DueGroup; tasks: Task[] }[] {
  const groups = new Map<DueGroup, Task[]>();
  for (const task of tasks) {
    const group = dueGroup(task.due_date, today);
    groups.set(group, [...(groups.get(group) ?? []), task]);
  }
  return [...groups].map(([group, grouped]) => ({ group, tasks: grouped }));
}
