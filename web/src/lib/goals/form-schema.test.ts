import { describe, expect, it } from "vitest";

import { makeGoal } from "@/test/goals-server";
import { goalFormSchema, toCreateBody, toFormValues, toPatchBody } from "./form-schema";
import { HORIZON_GUESS_WINDOW_MS, isGuessingHorizon } from "./queries";

describe("goal form → API bodies", () => {
  it("create: empty horizon, description and date become null (null horizon = AI guess)", () => {
    const values = goalFormSchema.parse({ title: "  Run a marathon ", description: "  ", horizon: "unset", targetDate: "" });

    expect(toCreateBody(values)).toEqual({ title: "Run a marathon", description: null, horizon: null, target_date: null });
  });

  it("patch: only dirty fields, so an untouched title is never sent (sticky flags)", () => {
    const values = goalFormSchema.parse({ title: "Same", description: "New text", horizon: "long_term", targetDate: "" });

    expect(toPatchBody(values, { description: true })).toEqual({ description: "New text" });
    expect(toPatchBody(values, { targetDate: true, horizon: true })).toEqual({ target_date: null, horizon: "long_term" });
    expect(toPatchBody(values, {})).toEqual({});
  });

  it("rejects an empty title", () => {
    const result = goalFormSchema.safeParse({ title: "   ", description: "", horizon: "unset", targetDate: "" });
    expect(result.success).toBe(false);
  });

  it("fills the form from a goal", () => {
    expect(toFormValues(makeGoal({ title: "T", description: null, horizon: null, target_date: "2027-01-01" }))).toEqual({
      title: "T",
      description: "",
      horizon: "unset",
      targetDate: "2027-01-01",
    });
  });
});

describe("isGuessingHorizon", () => {
  const created = new Date("2026-09-26T10:00:00Z");

  it("is true only for a goal with no horizon inside the window", () => {
    const goal = makeGoal({ horizon: null, created_at: created.toISOString() });
    expect(isGuessingHorizon(goal, created.getTime() + 1000)).toBe(true);
    expect(isGuessingHorizon(goal, created.getTime() + HORIZON_GUESS_WINDOW_MS)).toBe(false);
    expect(isGuessingHorizon({ ...goal, horizon: "short_term" }, created.getTime() + 1000)).toBe(false);
  });
});
