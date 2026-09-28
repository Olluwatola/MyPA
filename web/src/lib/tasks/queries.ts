"use client";

import {
  useInfiniteQuery,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { queryKeys, STALE_TIME } from "@/lib/api/query-config";
import type { components } from "@/lib/api/schema";
import { GUESS_POLL_MS, isInGuessWindow } from "@/lib/guess-window";
import { matchesFilters, STATUS_VIEWS, type Task, type TaskFilters, type TaskStatus } from "./labels";

type TasksPage = components["schemas"]["PaginatedListResponse_TaskRead_"];
type TaskCreate = components["schemas"]["TaskCreate"];
type TaskUpdate = components["schemas"]["TaskUpdate"];

const PAGE_SIZE = 50;
const CALENDAR_PAGE_SIZE = 100;
/** Safety cap for one calendar range: 10 pages = 1,000 tasks. */
export const CALENDAR_MAX_PAGES = 10;
/** Plan §1.7: a ticked task stays (ticked, struck through) this long before it leaves the view. */
export const DONE_LINGER_MS = 1200;
export const PENDING_ID_PREFIX = "pending-";

/** What's left of the pause for a task ticked at `startedAt` (none if it was sent later, offline). */
function lingerLeft(startedAt: number): number {
  return Math.max(DONE_LINGER_MS - (Date.now() - startedAt), 0);
}

/** Plan §1.5: urgency and/or effort still waiting for the AI guess. */
export function guessingFields(task: Task, now: number = Date.now()): { urgency: boolean; effort: boolean } {
  const inWindow = isInGuessWindow(task.created_at, now);
  return {
    urgency: inWindow && !task.urgency_manually_set,
    effort: inWindow && task.effort_level == null && !task.effort_level_manually_set,
  };
}

function isGuessing(task: Task): boolean {
  const { urgency, effort } = guessingFields(task);
  return urgency || effort;
}

const mutationKeys = {
  create: ["tasks", "create"],
  update: ["tasks", "update"],
  status: ["tasks", "status"],
  delete: ["tasks", "delete"],
} as const;

function listQuery(filters: TaskFilters) {
  const status = STATUS_VIEWS[filters.status].status;
  return {
    ...(status && { status }),
    ...(filters.source && { source: filters.source }),
    ...(filters.urgency && { urgency: filters.urgency }),
  };
}

// ---------------------------------------------------------------- queries

export function useTasksList(filters: TaskFilters) {
  return useInfiniteQuery({
    queryKey: queryKeys.tasks.list(filters),
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/tasks", {
          params: { query: { page: pageParam, items_per_page: PAGE_SIZE, ...listQuery(filters) } },
        }),
      ),
    initialPageParam: 1,
    getNextPageParam: (last: TasksPage, _all, lastPageParam: number) => (last.has_more ? lastPageParam + 1 : undefined),
    staleTime: STALE_TIME.tasks,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.data.some(isGuessing)) ? GUESS_POLL_MS : false,
  });
}

/** Every task due in `[from, to]` (inclusive `YYYY-MM-DD`), all pages up to the cap. */
export function useCalendarTasks(range: { from: string; to: string }, filters: TaskFilters, enabled = true) {
  return useQuery({
    enabled,
    queryKey: queryKeys.tasks.calendar(range, filters),
    queryFn: async () => {
      const tasks: Task[] = [];
      for (let page = 1; page <= CALENDAR_MAX_PAGES; page++) {
        const result = unwrap(
          await api.GET("/api/v1/tasks", {
            params: {
              query: {
                page,
                items_per_page: CALENDAR_PAGE_SIZE,
                due_from: range.from,
                due_to: range.to,
                ...listQuery(filters),
              },
            },
          }),
        );
        tasks.push(...result.data);
        if (!result.has_more) return { tasks, capped: false };
      }
      return { tasks, capped: true };
    },
    staleTime: STALE_TIME.tasks,
    placeholderData: (previous) => previous,
  });
}

function findCached(queryClient: QueryClient, id: string): Task | undefined {
  for (const [, data] of queryClient.getQueriesData<InfiniteData<TasksPage>>({ queryKey: queryKeys.tasks.lists })) {
    const task = data?.pages.flatMap((page) => page.data).find((t) => t.id === id);
    if (task) return task;
  }
  return undefined;
}

export function useTask(id: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.tasks.detail(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/api/v1/tasks/{task_id}", { params: { path: { task_id: id! } } })),
    enabled: id !== null && !id.startsWith(PENDING_ID_PREFIX),
    // The panel opens instantly from the list row; the fetch then checks it's current.
    initialData: () => (id ? findCached(queryClient, id) : undefined),
    initialDataUpdatedAt: 0,
    staleTime: STALE_TIME.tasks,
    refetchInterval: (query) => (query.state.data && isGuessing(query.state.data) ? GUESS_POLL_MS : false),
  });
}

// ---------------------------------------------------------------- cache helpers

type Snapshot = [QueryKey, unknown][];

async function snapshotTasks(queryClient: QueryClient): Promise<Snapshot> {
  await queryClient.cancelQueries({ queryKey: queryKeys.tasks.all });
  return queryClient.getQueriesData({ queryKey: queryKeys.tasks.all });
}

function restore(queryClient: QueryClient, snapshot: Snapshot | undefined) {
  snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data));
}

/** Applies `change` to the task in every cached list and calendar; `null` removes it there. */
function editCached(queryClient: QueryClient, id: string, change: (task: Task, filters: TaskFilters) => Task | null) {
  const apply = (tasks: Task[], filters: TaskFilters) =>
    tasks.flatMap((task) => {
      if (task.id !== id) return [task];
      const next = change(task, filters);
      return next ? [next] : [];
    });

  queryClient
    .getQueryCache()
    .findAll({ queryKey: queryKeys.tasks.lists })
    .forEach((query) => {
      const filters = query.queryKey[2] as TaskFilters;
      queryClient.setQueryData<InfiniteData<TasksPage>>(query.queryKey, (data) =>
        data ? { ...data, pages: data.pages.map((page) => ({ ...page, data: apply(page.data, filters) })) } : data,
      );
    });
  queryClient
    .getQueryCache()
    .findAll({ queryKey: queryKeys.tasks.calendars })
    .forEach((query) => {
      const filters = query.queryKey[3] as TaskFilters;
      queryClient.setQueryData<{ tasks: Task[]; capped: boolean }>(query.queryKey, (data) =>
        data ? { ...data, tasks: apply(data.tasks, filters) } : data,
      );
    });
}

function refreshAround(queryClient: QueryClient, goalIds: (string | null | undefined)[]) {
  queryClient.invalidateQueries({ queryKey: queryKeys.tasks.lists });
  queryClient.invalidateQueries({ queryKey: queryKeys.tasks.calendars });
  for (const goalId of new Set(goalIds)) {
    if (goalId) queryClient.invalidateQueries({ queryKey: queryKeys.tasks.byGoal(goalId) });
  }
}

// ---------------------------------------------------------------- mutations
// All of them pause while offline (TanStack's default networkMode) and show "Waiting to send".
// Failures get the global toast (query-config.ts).

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.create,
    mutationFn: async ({ body }: { body: TaskCreate; tempId: string }) =>
      unwrap(await api.POST("/api/v1/tasks", { body })),
    onMutate: async ({ body, tempId }) => {
      const snapshot = await snapshotTasks(queryClient);
      const temp: Task = {
        id: tempId,
        title: body.title,
        description: body.description ?? null,
        due_date: body.due_date ?? null,
        status: "open",
        source: "manual",
        urgency: body.urgency ?? "medium",
        effort_level: body.effort_level ?? null,
        memory_record_id: null,
        scheduled_event_id: null,
        goal_id: body.goal_id ?? null,
        created_at: new Date().toISOString(),
        title_manually_set: false,
        description_manually_set: false,
        urgency_manually_set: body.urgency != null,
        effort_level_manually_set: body.effort_level != null,
        goal_id_manually_set: body.goal_id != null,
      };
      queryClient
        .getQueryCache()
        .findAll({ queryKey: queryKeys.tasks.lists })
        .forEach((query) => {
          if (!matchesFilters(temp, query.queryKey[2] as TaskFilters)) return;
          queryClient.setQueryData<InfiniteData<TasksPage>>(query.queryKey, (data) =>
            data
              ? { ...data, pages: data.pages.map((page, i) => (i === 0 ? { ...page, data: [temp, ...page.data] } : page)) }
              : data,
          );
        });
      return { snapshot };
    },
    onSuccess: (task, { tempId }) => {
      editCached(queryClient, tempId, () => task);
      queryClient.setQueryData(queryKeys.tasks.detail(task.id), task);
      // Refetch so the new task takes its place in the due-date order.
      refreshAround(queryClient, [task.goal_id]);
      toast.success("Task added");
    },
    onError: (_error, _vars, context) => restore(queryClient, context?.snapshot),
  });
}

export function useUpdateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.update,
    mutationFn: async ({ id, body }: { id: string; body: TaskUpdate; previousGoalId: string | null }) =>
      unwrap(await api.PATCH("/api/v1/tasks/{task_id}", { params: { path: { task_id: id } }, body })),
    // Lists update at once. The detail (which the open form is built from) only changes when the
    // server confirms, so a failed save never resets the form (decisions-log 2026-09-26).
    onMutate: async ({ id, body }) => {
      const snapshot = await snapshotTasks(queryClient);
      editCached(queryClient, id, (task) => ({
        ...task,
        ...body,
        title: body.title ?? task.title,
        urgency: body.urgency ?? task.urgency,
      }));
      return { snapshot };
    },
    onSuccess: (task, { previousGoalId }) => {
      queryClient.setQueryData(queryKeys.tasks.detail(task.id), task);
      refreshAround(queryClient, [previousGoalId, task.goal_id]);
    },
    onError: (_error, _vars, context) => restore(queryClient, context?.snapshot),
  });
}

export function useSetTaskStatus() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationKey: mutationKeys.status,
    mutationFn: async ({ id, status }: { id: string; status: TaskStatus; previous: TaskStatus; startedAt: number }) =>
      unwrap(
        await api.PATCH("/api/v1/tasks/{task_id}/status", { params: { path: { task_id: id } }, body: { status } }),
      ),
    // The task is ticked everywhere at once but stays in view; it only leaves a list it no longer
    // matches once the change is sent and the short pause is over (plan §1.7).
    onMutate: async ({ id, status }) => {
      const snapshot = await snapshotTasks(queryClient);
      editCached(queryClient, id, (task) => ({ ...task, status }));
      queryClient.setQueryData<Task>(queryKeys.tasks.detail(id), (task) => task && { ...task, status });
      return { snapshot };
    },
    onSuccess: (task, { id, status, previous, startedAt }) => {
      queryClient.setQueryData(queryKeys.tasks.detail(id), task);
      // Lists that don't show the task (e.g. Open after it left, then Undo) fetch it back now;
      // only leaving a list waits for the pause.
      queryClient.invalidateQueries({
        queryKey: queryKeys.tasks.lists,
        predicate: (query) =>
          !(query.state.data as InfiniteData<TasksPage> | undefined)?.pages.some((page) =>
            page.data.some((cached) => cached.id === id),
          ),
      });
      setTimeout(() => {
        // Checks the cached status now, so an Undo during the pause keeps the task in place.
        editCached(queryClient, id, (cached, filters) => (matchesFilters(cached, filters) ? cached : null));
        refreshAround(queryClient, [task.goal_id]);
      }, lingerLeft(startedAt));
      toast(status === "done" ? "Marked done" : "Marked not done", {
        duration: 5000,
        action: {
          label: "Undo",
          onClick: () => mutation.mutate({ id, status: previous, previous: status, startedAt: Date.now() }),
        },
      });
    },
    onError: (_error, _vars, context) => restore(queryClient, context?.snapshot),
  });
  return mutation;
}

export function useDeleteTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.delete,
    mutationFn: async ({ id }: { id: string; goalId: string | null }) =>
      unwrap(await api.DELETE("/api/v1/tasks/{task_id}", { params: { path: { task_id: id } } })),
    onSuccess: (_data, { id, goalId }) => {
      editCached(queryClient, id, () => null);
      queryClient.removeQueries({ queryKey: queryKeys.tasks.detail(id) });
      if (goalId) queryClient.invalidateQueries({ queryKey: queryKeys.tasks.byGoal(goalId) });
      toast.success("Task deleted");
    },
  });
}

// ---------------------------------------------------------------- waiting to send

export type PendingKind = "send" | "delete";

/** Task ids with a mutation paused by being offline (design-system.md §7.6). */
export function usePendingTasks(): Map<string, PendingKind> {
  const paused = useMutationState({
    filters: { mutationKey: ["tasks"], predicate: (mutation) => mutation.state.isPaused },
    select: (mutation) => {
      const variables = mutation.state.variables as { id?: string; tempId?: string };
      const kind: PendingKind = mutation.options.mutationKey?.[1] === "delete" ? "delete" : "send";
      return [variables.id ?? variables.tempId ?? "", kind] as const;
    },
  });
  return new Map(paused);
}
