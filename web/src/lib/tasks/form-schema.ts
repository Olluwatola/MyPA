import { z } from "zod";

import type { components } from "@/lib/api/schema";
import type { Task } from "./labels";

type TaskCreate = components["schemas"]["TaskCreate"];
type TaskUpdate = components["schemas"]["TaskUpdate"];

// Mirrors the backend's TaskCreate / TaskUpdate so errors show instantly.
export const taskFormSchema = z.object({
  title: z.string().trim().min(1, "Give the task a title.").max(255, "Use 255 characters or fewer."),
  description: z.string(),
  /** `""` or `YYYY-MM-DD` (native date input). */
  dueDate: z.string(),
  /** "suggest" = let the AI guess (create only; the backend never accepts an empty urgency on edit). */
  urgency: z.enum(["suggest", "low", "medium", "high"]),
  /** "suggest" = let the AI guess (create); "none" = not set (edit). */
  effort: z.enum(["suggest", "none", "deep_focus", "light_focus", "passive"]),
  /** A goal id, or "none". */
  goalId: z.string(),
});

export type TaskFormInput = z.input<typeof taskFormSchema>;
export type TaskFormValues = z.output<typeof taskFormSchema>;

export const EMPTY_TASK_FORM: TaskFormInput = {
  title: "",
  description: "",
  dueDate: "",
  urgency: "suggest",
  effort: "suggest",
  goalId: "none",
};

export function toFormValues(task: Task): TaskFormInput {
  return {
    title: task.title,
    description: task.description ?? "",
    dueDate: task.due_date ?? "",
    urgency: task.urgency,
    effort: task.effort_level ?? "none",
    goalId: task.goal_id ?? "none",
  };
}

function toApi(values: TaskFormValues) {
  return {
    title: values.title,
    description: values.description.trim() || null,
    due_date: values.dueDate || null,
    urgency: values.urgency === "suggest" ? null : values.urgency,
    effort_level: values.effort === "suggest" || values.effort === "none" ? null : values.effort,
    goal_id: values.goalId === "none" ? null : values.goalId,
  };
}

/** `urgency`/`effort_level: null` asks the backend to guess them in the background. */
export function toCreateBody(values: TaskFormValues): TaskCreate {
  return toApi(values);
}

type Dirty = Partial<Record<keyof TaskFormValues, boolean | undefined>>;

/**
 * Only the fields the user changed. The backend marks every field it receives as set by hand
 * (sticky), so an untouched field must never be sent.
 */
export function toPatchBody(values: TaskFormValues, dirty: Dirty): TaskUpdate {
  const api = toApi(values);
  const body: TaskUpdate = {};
  if (dirty.title) body.title = api.title;
  if (dirty.description) body.description = api.description;
  if (dirty.dueDate) body.due_date = api.due_date;
  if (dirty.urgency && api.urgency !== null) body.urgency = api.urgency;
  if (dirty.effort) body.effort_level = api.effort_level;
  if (dirty.goalId) body.goal_id = api.goal_id;
  return body;
}
