import { z } from "zod";

import type { components } from "@/lib/api/schema";
import type { Goal } from "./labels";

type GoalCreate = components["schemas"]["GoalCreate"];
type GoalUpdate = components["schemas"]["GoalUpdate"];

// Mirrors the backend's GoalCreate / GoalUpdate so errors show instantly.
export const goalFormSchema = z.object({
  title: z.string().trim().min(1, "Give the goal a title.").max(255, "Use 255 characters or fewer."),
  description: z.string(),
  /** "unset" = no horizon: "Let MyPA suggest" when creating, "Not set" when editing. */
  horizon: z.enum(["unset", "short_term", "long_term"]),
  /** `""` or `YYYY-MM-DD` (native date input). */
  targetDate: z.string(),
});

export type GoalFormInput = z.input<typeof goalFormSchema>;
export type GoalFormValues = z.output<typeof goalFormSchema>;

export const EMPTY_GOAL_FORM: GoalFormInput = { title: "", description: "", horizon: "unset", targetDate: "" };

export function toFormValues(goal: Goal): GoalFormInput {
  return {
    title: goal.title,
    description: goal.description ?? "",
    horizon: goal.horizon ?? "unset",
    targetDate: goal.target_date ?? "",
  };
}

function toApi(values: GoalFormValues) {
  return {
    title: values.title,
    description: values.description.trim() || null,
    horizon: values.horizon === "unset" ? null : values.horizon,
    target_date: values.targetDate || null,
  };
}

/** `horizon: null` asks the backend to guess it in the background. */
export function toCreateBody(values: GoalFormValues): GoalCreate {
  return toApi(values);
}

type Dirty = Partial<Record<keyof GoalFormValues, boolean | undefined>>;

/**
 * Only the fields the user changed. Re-sending an untouched title or description would mark it
 * as set by hand (the backend's sticky `*_manually_set` flags), so it must never be sent.
 */
export function toPatchBody(values: GoalFormValues, dirty: Dirty): GoalUpdate {
  const api = toApi(values);
  const body: GoalUpdate = {};
  if (dirty.title) body.title = api.title;
  if (dirty.description) body.description = api.description;
  if (dirty.horizon) body.horizon = api.horizon;
  if (dirty.targetDate) body.target_date = api.target_date;
  return body;
}
