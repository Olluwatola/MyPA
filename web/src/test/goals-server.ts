import { http, HttpResponse } from "msw";

import type { components } from "@/lib/api/schema";
import { API, server } from "./server";

type Goal = components["schemas"]["GoalRead"];
type Task = components["schemas"]["TaskRead"];

/** An in-memory stand-in for the goal routes (backend api/v1/goals.py), newest first. */
export const goalsDb = {
  goals: [] as Goal[],
  tasks: [] as Task[],
  /** Request bodies the app sent, by "METHOD /path". */
  bodies: new Map<string, unknown[]>(),
};

let counter = 0;

export function makeGoal(overrides: Partial<Goal> = {}): Goal {
  counter += 1;
  return {
    id: `00000000-0000-7000-8000-${String(counter).padStart(12, "0")}`,
    title: `Goal ${counter}`,
    description: null,
    status: "open",
    source: "manual",
    horizon: "short_term",
    target_date: null,
    memory_record_id: null,
    // An hour ago: well outside the horizon-guess window.
    created_at: new Date(Date.now() - 3_600_000).toISOString(),
    title_manually_set: false,
    description_manually_set: false,
    ...overrides,
  };
}

export function makeTask(overrides: Partial<Task> = {}): Task {
  counter += 1;
  return {
    id: `00000000-0000-7000-9000-${String(counter).padStart(12, "0")}`,
    title: `Task ${counter}`,
    description: null,
    due_date: null,
    status: "open",
    source: "manual",
    urgency: "low",
    effort_level: null,
    memory_record_id: null,
    scheduled_event_id: null,
    goal_id: null,
    // An hour ago: well outside the AI-guess window.
    created_at: new Date(Date.now() - 3_600_000).toISOString(),
    title_manually_set: false,
    description_manually_set: false,
    urgency_manually_set: false,
    effort_level_manually_set: false,
    goal_id_manually_set: false,
    ...overrides,
  };
}

export function record(key: string, body: unknown) {
  goalsDb.bodies.set(key, [...(goalsDb.bodies.get(key) ?? []), body]);
}

export function sentBodies(key: string): unknown[] {
  return goalsDb.bodies.get(key) ?? [];
}

function find(id: string) {
  return goalsDb.goals.find((goal) => goal.id === id);
}

const notFound = () => HttpResponse.json({ detail: "Goal not found." }, { status: 404 });

export function serveGoals(...goals: Goal[]) {
  goalsDb.goals = goals;
  goalsDb.tasks = [];
  goalsDb.bodies = new Map();

  server.use(
    http.get(`${API}/goals`, ({ request }) => {
      const url = new URL(request.url);
      record("GET /goals", url.search);
      const statuses = url.searchParams.getAll("status");
      const page = Number(url.searchParams.get("page") ?? 1);
      const perPage = Number(url.searchParams.get("items_per_page") ?? 20);
      const matching = goalsDb.goals.filter((goal) => statuses.length === 0 || statuses.includes(goal.status));
      const data = matching.slice((page - 1) * perPage, page * perPage);
      return HttpResponse.json({
        data,
        total_count: matching.length,
        has_more: page * perPage < matching.length,
        page,
        items_per_page: perPage,
      });
    }),
    http.get(`${API}/goals/:id`, ({ params }) => {
      const goal = find(params.id as string);
      return goal ? HttpResponse.json(goal) : notFound();
    }),
    http.post(`${API}/goals`, async ({ request }) => {
      const body = (await request.json()) as Partial<Goal>;
      record("POST /goals", body);
      const goal = makeGoal({ ...body, created_at: new Date().toISOString() });
      goalsDb.goals = [goal, ...goalsDb.goals];
      return HttpResponse.json(goal, { status: 201 });
    }),
    http.patch(`${API}/goals/:id`, async ({ params, request }) => {
      const body = (await request.json()) as Partial<Goal>;
      record(`PATCH /goals/${params.id}`, body);
      const goal = find(params.id as string);
      if (!goal) return notFound();
      Object.assign(goal, body);
      if ("title" in body) goal.title_manually_set = true;
      if ("description" in body) goal.description_manually_set = true;
      return HttpResponse.json(goal);
    }),
    http.patch(`${API}/goals/:id/status`, async ({ params, request }) => {
      const body = (await request.json()) as { status: Goal["status"] };
      record(`PATCH /goals/${params.id}/status`, body);
      const goal = find(params.id as string);
      if (!goal) return notFound();
      goal.status = body.status;
      return HttpResponse.json(goal);
    }),
    http.delete(`${API}/goals/:id`, ({ params }) => {
      record(`DELETE /goals/${params.id}`, null);
      if (!find(params.id as string)) return notFound();
      goalsDb.goals = goalsDb.goals.filter((goal) => goal.id !== params.id);
      goalsDb.tasks.forEach((task) => {
        if (task.goal_id === params.id) task.goal_id = null;
      });
      return HttpResponse.json({ message: "Goal deleted." });
    }),
    http.get(`${API}/tasks`, ({ request }) => {
      const goalId = new URL(request.url).searchParams.get("goal_id");
      const data = goalsDb.tasks.filter((task) => task.goal_id === goalId);
      return HttpResponse.json({ data, total_count: data.length, has_more: false, page: 1, items_per_page: 50 });
    }),
  );
}
