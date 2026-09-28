import { http, HttpResponse } from "msw";

import type { components } from "@/lib/api/schema";
import { goalsDb, makeTask, record } from "./goals-server";
import { API, server } from "./server";

type Task = components["schemas"]["TaskRead"];

/**
 * An in-memory stand-in for the task routes (backend api/v1/tasks.py). Shares `goalsDb`, so
 * deleting a goal un-links its tasks, as the backend does. Call after `serveGoals`.
 */
export function serveTasks(...tasks: Task[]) {
  goalsDb.tasks = tasks;
  const find = (id: string) => goalsDb.tasks.find((task) => task.id === id);
  const notFound = () => HttpResponse.json({ detail: "Task not found." }, { status: 404 });

  // Backend order: open first, then soonest due date (no date last), then newest.
  const order = (a: Task, b: Task) =>
    b.status.localeCompare(a.status) ||
    (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999") ||
    b.created_at.localeCompare(a.created_at);

  server.use(
    http.get(`${API}/tasks`, ({ request }) => {
      const url = new URL(request.url);
      record("GET /tasks", url.search);
      const q = (key: string) => url.searchParams.get(key);
      const matching = goalsDb.tasks
        .filter(
          (task) =>
            (!q("status") || task.status === q("status")) &&
            (!q("source") || task.source === q("source")) &&
            (!q("urgency") || task.urgency === q("urgency")) &&
            (!q("goal_id") || task.goal_id === q("goal_id")) &&
            (!q("due_from") || (task.due_date !== null && task.due_date! >= q("due_from")!)) &&
            (!q("due_to") || (task.due_date !== null && task.due_date! <= q("due_to")!)),
        )
        .sort(order);
      const page = Number(q("page") ?? 1);
      const perPage = Number(q("items_per_page") ?? 20);
      return HttpResponse.json({
        data: matching.slice((page - 1) * perPage, page * perPage),
        total_count: matching.length,
        has_more: page * perPage < matching.length,
        page,
        items_per_page: perPage,
      });
    }),
    http.get(`${API}/tasks/:id`, ({ params }) => {
      const task = find(params.id as string);
      return task ? HttpResponse.json(task) : notFound();
    }),
    http.post(`${API}/tasks`, async ({ request }) => {
      const body = (await request.json()) as Partial<Task>;
      record("POST /tasks", body);
      const task = makeTask({
        ...body,
        urgency: body.urgency ?? "medium",
        created_at: new Date().toISOString(),
        urgency_manually_set: body.urgency != null,
        effort_level_manually_set: body.effort_level != null,
        goal_id_manually_set: body.goal_id != null,
      });
      goalsDb.tasks = [task, ...goalsDb.tasks];
      return HttpResponse.json(task, { status: 201 });
    }),
    http.patch(`${API}/tasks/:id`, async ({ params, request }) => {
      const body = (await request.json()) as Partial<Task>;
      record(`PATCH /tasks/${params.id}`, body);
      const task = find(params.id as string);
      if (!task) return notFound();
      Object.assign(task, body);
      // Every edited field becomes sticky (core/items/sticky.py).
      if ("title" in body) task.title_manually_set = true;
      if ("description" in body) task.description_manually_set = true;
      if ("urgency" in body) task.urgency_manually_set = true;
      if ("effort_level" in body) task.effort_level_manually_set = true;
      if ("goal_id" in body) task.goal_id_manually_set = true;
      return HttpResponse.json(task);
    }),
    http.patch(`${API}/tasks/:id/status`, async ({ params, request }) => {
      const body = (await request.json()) as { status: Task["status"] };
      record(`PATCH /tasks/${params.id}/status`, body);
      const task = find(params.id as string);
      if (!task) return notFound();
      task.status = body.status;
      return HttpResponse.json(task);
    }),
    http.delete(`${API}/tasks/:id`, ({ params }) => {
      record(`DELETE /tasks/${params.id}`, null);
      if (!find(params.id as string)) return notFound();
      goalsDb.tasks = goalsDb.tasks.filter((task) => task.id !== params.id);
      return HttpResponse.json({ message: "Task deleted." });
    }),
  );
}
