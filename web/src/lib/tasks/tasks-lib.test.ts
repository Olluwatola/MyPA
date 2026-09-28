import { describe, expect, it } from "vitest";

import { todayIn } from "@/lib/format/date";
import { makeTask } from "@/test/goals-server";
import { dueGroup, groupTasks } from "./due-groups";
import { taskFormSchema, toCreateBody, toFormValues, toPatchBody } from "./form-schema";
import { matchesFilters, parseTaskSearch } from "./labels";
import { guessingFields } from "./queries";

describe("dueGroup", () => {
  const today = "2026-09-26";

  it.each([
    [null, "none"],
    ["2026-09-25", "overdue"],
    ["2026-09-26", "today"],
    ["2026-09-27", "tomorrow"],
    ["2026-09-28", "next7"],
    ["2026-10-03", "next7"],
    ["2026-10-04", "later"],
  ] as const)("%s → %s", (due, group) => {
    expect(dueGroup(due, today)).toBe(group);
  });

  it("uses the user's own 'today', not UTC's", () => {
    // 23:30 UTC on the 25th is already the 26th in Lagos but still the 25th in New York.
    const now = new Date("2026-09-25T23:30:00Z");
    expect(dueGroup("2026-09-26", todayIn("Africa/Lagos", now))).toBe("today");
    expect(dueGroup("2026-09-26", todayIn("America/New_York", now))).toBe("tomorrow");
  });

  it("groups a sorted list in order, keeping each task's place", () => {
    const tasks = [
      makeTask({ title: "a", due_date: "2026-09-20" }),
      makeTask({ title: "b", due_date: "2026-09-26" }),
      makeTask({ title: "c", due_date: "2026-09-26" }),
      makeTask({ title: "d", due_date: null }),
    ];

    expect(groupTasks(tasks, "2026-09-26").map(({ group, tasks: t }) => [group, t.map((x) => x.title)])).toEqual([
      ["overdue", ["a"]],
      ["today", ["b", "c"]],
      ["none", ["d"]],
    ]);
  });
});

describe("task form → API bodies", () => {
  it("create: 'Let MyPA suggest' and empty fields become null", () => {
    const values = taskFormSchema.parse({
      title: " Send the proposal ",
      description: "",
      dueDate: "",
      urgency: "suggest",
      effort: "suggest",
      goalId: "none",
    });

    expect(toCreateBody(values)).toEqual({
      title: "Send the proposal",
      description: null,
      due_date: null,
      urgency: null,
      effort_level: null,
      goal_id: null,
    });
  });

  it("patch: only dirty fields; unlinking the goal and clearing effort send null", () => {
    const values = taskFormSchema.parse({
      title: "Same",
      description: "",
      dueDate: "2026-10-01",
      urgency: "high",
      effort: "none",
      goalId: "none",
    });

    expect(toPatchBody(values, { goalId: true })).toEqual({ goal_id: null });
    expect(toPatchBody(values, { effort: true, urgency: true })).toEqual({ effort_level: null, urgency: "high" });
    expect(toPatchBody(values, {})).toEqual({});
  });

  it("fills the form from a task", () => {
    const task = makeTask({ urgency: "high", effort_level: null, goal_id: null, due_date: "2026-10-01" });
    expect(toFormValues(task)).toMatchObject({ urgency: "high", effort: "none", goalId: "none", dueDate: "2026-10-01" });
  });
});

describe("parseTaskSearch / matchesFilters", () => {
  it("falls back to defaults for unknown values", () => {
    expect(parseTaskSearch(new URLSearchParams("view=grid&status=weird&source=fax&urgency=max&date=soon"))).toEqual({
      view: "list",
      status: "open",
      source: null,
      urgency: null,
      cal: "month",
      date: null,
      task: null,
    });
  });

  it("reads a full URL", () => {
    expect(
      parseTaskSearch(new URLSearchParams("view=calendar&status=all&source=email&urgency=high&cal=week&date=2026-10-01&task=x")),
    ).toEqual({ view: "calendar", status: "all", source: "email", urgency: "high", cal: "week", date: "2026-10-01", task: "x" });
  });

  it("checks status, source and urgency", () => {
    const task = makeTask({ status: "open", source: "email", urgency: "high" });
    expect(matchesFilters(task, { status: "open", source: "email", urgency: "high" })).toBe(true);
    expect(matchesFilters(task, { status: "all", source: null, urgency: null })).toBe(true);
    expect(matchesFilters(task, { status: "done", source: null, urgency: null })).toBe(false);
    expect(matchesFilters(task, { status: "open", source: "notion", urgency: null })).toBe(false);
  });
});

describe("guessingFields", () => {
  const created = new Date("2026-09-26T10:00:00Z");
  const soon = created.getTime() + 1000;

  it("urgency and effort are guessed only when the user left them empty, inside the window", () => {
    const fresh = makeTask({ created_at: created.toISOString(), effort_level: null });
    expect(guessingFields(fresh, soon)).toEqual({ urgency: true, effort: true });
    expect(guessingFields({ ...fresh, urgency_manually_set: true }, soon)).toEqual({ urgency: false, effort: true });
    expect(guessingFields({ ...fresh, effort_level: "passive" }, soon)).toEqual({ urgency: true, effort: false });
    expect(guessingFields(fresh, created.getTime() + 20_000)).toEqual({ urgency: false, effort: false });
  });
});
