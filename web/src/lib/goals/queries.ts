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
import { STATUS_LABEL, VIEWS, viewIncludes, type Goal, type GoalStatus, type GoalView } from "./labels";

type GoalsPage = components["schemas"]["PaginatedListResponse_GoalRead_"];
type GoalCreate = components["schemas"]["GoalCreate"];
type GoalUpdate = components["schemas"]["GoalUpdate"];
export type LinkedTask = components["schemas"]["TaskRead"];

const PAGE_SIZE = 50;

// Plan §1.4: a new goal left without a horizon gets one from the AI in the background. While that
// can still arrive, the goal's queries re-check every few seconds.
export const HORIZON_GUESS_WINDOW_MS = 20_000;
const HORIZON_POLL_MS = 3000;

export function isGuessingHorizon(goal: Goal, now: number = Date.now()): boolean {
  return goal.horizon == null && now - new Date(goal.created_at).getTime() < HORIZON_GUESS_WINDOW_MS;
}

export const PENDING_ID_PREFIX = "pending-";

const mutationKeys = {
  create: ["goals", "create"],
  update: ["goals", "update"],
  status: ["goals", "status"],
  delete: ["goals", "delete"],
} as const;

// ---------------------------------------------------------------- queries

export function useGoalsList(view: GoalView) {
  return useInfiniteQuery({
    queryKey: queryKeys.goals.list(view),
    queryFn: async ({ pageParam }) => {
      const statuses = VIEWS[view].statuses;
      return unwrap(
        await api.GET("/api/v1/goals", {
          params: {
            query: { page: pageParam, items_per_page: PAGE_SIZE, ...(statuses && { status: [...statuses] }) },
          },
        }),
      );
    },
    initialPageParam: 1,
    getNextPageParam: (last: GoalsPage, _all, lastPageParam: number) => (last.has_more ? lastPageParam + 1 : undefined),
    staleTime: STALE_TIME.goals,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.data.some((goal) => isGuessingHorizon(goal))) ? HORIZON_POLL_MS : false,
  });
}

function findInLists(queryClient: QueryClient, id: string): Goal | undefined {
  for (const [, data] of queryClient.getQueriesData<InfiniteData<GoalsPage>>({ queryKey: queryKeys.goals.lists })) {
    const goal = data?.pages.flatMap((page) => page.data).find((g) => g.id === id);
    if (goal) return goal;
  }
  return undefined;
}

export function useGoal(id: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.goals.detail(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/api/v1/goals/{goal_id}", { params: { path: { goal_id: id! } } })),
    enabled: id !== null && !id.startsWith(PENDING_ID_PREFIX),
    // The panel opens instantly from the list row; the fetch then checks it's current.
    initialData: () => (id ? findInLists(queryClient, id) : undefined),
    initialDataUpdatedAt: 0,
    staleTime: STALE_TIME.goals,
    refetchInterval: (query) => (query.state.data && isGuessingHorizon(query.state.data) ? HORIZON_POLL_MS : false),
  });
}

export function useLinkedTasks(goalId: string) {
  return useQuery({
    queryKey: queryKeys.tasks.byGoal(goalId),
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/tasks", { params: { query: { goal_id: goalId, items_per_page: 50 } } })),
    staleTime: STALE_TIME.tasks,
  });
}

// ---------------------------------------------------------------- cache helpers

type Snapshot = [QueryKey, unknown][];

async function snapshotGoals(queryClient: QueryClient): Promise<Snapshot> {
  await queryClient.cancelQueries({ queryKey: queryKeys.goals.all });
  return queryClient.getQueriesData({ queryKey: queryKeys.goals.all });
}

function restore(queryClient: QueryClient, snapshot: Snapshot | undefined) {
  snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data));
}

/** Applies `change` to every cached list; `null` removes the goal from that list. */
function editLists(queryClient: QueryClient, change: (goal: Goal, view: GoalView) => Goal | null, id: string) {
  queryClient
    .getQueryCache()
    .findAll({ queryKey: queryKeys.goals.lists })
    .forEach((query) => {
      const view = query.queryKey[2] as GoalView;
      queryClient.setQueryData<InfiniteData<GoalsPage>>(query.queryKey, (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                data: page.data.flatMap((goal) => {
                  if (goal.id !== id) return [goal];
                  const next = change(goal, view);
                  return next ? [next] : [];
                }),
              })),
            }
          : data,
      );
    });
}

function putGoal(queryClient: QueryClient, goal: Goal, replacingId: string = goal.id) {
  queryClient.setQueryData(queryKeys.goals.detail(goal.id), goal);
  editLists(queryClient, (_, view) => (viewIncludes(view, goal.status) ? goal : null), replacingId);
}

// ---------------------------------------------------------------- mutations
// All of them pause while offline (TanStack's default networkMode) and show "Waiting to send".
// Failures get the global toast (query-config.ts).

export function useCreateGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.create,
    mutationFn: async ({ body }: { body: GoalCreate; tempId: string }) =>
      unwrap(await api.POST("/api/v1/goals", { body })),
    onMutate: async ({ body, tempId }) => {
      const snapshot = await snapshotGoals(queryClient);
      const temp: Goal = {
        id: tempId,
        title: body.title,
        description: body.description ?? null,
        horizon: body.horizon ?? null,
        target_date: body.target_date ?? null,
        status: "open",
        source: "manual",
        memory_record_id: null,
        created_at: new Date().toISOString(),
        title_manually_set: false,
        description_manually_set: false,
      };
      for (const view of ["active", "all"] as const) {
        queryClient.setQueryData<InfiniteData<GoalsPage>>(queryKeys.goals.list(view), (data) =>
          data
            ? { ...data, pages: data.pages.map((page, i) => (i === 0 ? { ...page, data: [temp, ...page.data] } : page)) }
            : data,
        );
      }
      return { snapshot };
    },
    onSuccess: (goal, { tempId }) => {
      putGoal(queryClient, goal, tempId);
      toast.success("Goal added");
    },
    onError: (_error, _vars, context) => restore(queryClient, context?.snapshot),
  });
}

export function useUpdateGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.update,
    mutationFn: async ({ id, body }: { id: string; body: GoalUpdate }) =>
      unwrap(await api.PATCH("/api/v1/goals/{goal_id}", { params: { path: { goal_id: id } }, body })),
    // Lists update at once. The detail (which the open form is built from) only changes when the
    // server confirms, so a failed save never resets the form and loses the user's edits.
    onMutate: async ({ id, body }) => {
      const snapshot = await snapshotGoals(queryClient);
      editLists(queryClient, (goal) => ({ ...goal, ...body, title: body.title ?? goal.title }), id);
      return { snapshot };
    },
    onSuccess: (goal) => putGoal(queryClient, goal),
    onError: (_error, _vars, context) => restore(queryClient, context?.snapshot),
  });
}

export function useSetGoalStatus() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationKey: mutationKeys.status,
    mutationFn: async ({ id, status }: { id: string; status: GoalStatus; previous: GoalStatus }) =>
      unwrap(
        await api.PATCH("/api/v1/goals/{goal_id}/status", { params: { path: { goal_id: id } }, body: { status } }),
      ),
    onMutate: async ({ id, status }) => {
      const snapshot = await snapshotGoals(queryClient);
      queryClient.setQueryData<Goal>(queryKeys.goals.detail(id), (goal) => goal && { ...goal, status });
      // A goal marked done leaves the Active list at once.
      editLists(queryClient, (goal, view) => (viewIncludes(view, status) ? { ...goal, status } : null), id);
      return { snapshot };
    },
    onSuccess: (goal, { id, status, previous }) => {
      queryClient.setQueryData(queryKeys.goals.detail(id), goal);
      toast(`Marked ${STATUS_LABEL[status].toLowerCase()}`, {
        action: { label: "Undo", onClick: () => mutation.mutate({ id, status: previous, previous: status }) },
      });
    },
    onError: (_error, _vars, context) => restore(queryClient, context?.snapshot),
    // Lists it should now appear in (e.g. Done) are fetched fresh.
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.goals.lists }),
  });
  return mutation;
}

export function useDeleteGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.delete,
    mutationFn: async ({ id }: { id: string }) =>
      unwrap(await api.DELETE("/api/v1/goals/{goal_id}", { params: { path: { goal_id: id } } })),
    onSuccess: (_data, { id }) => {
      editLists(queryClient, () => null, id);
      queryClient.removeQueries({ queryKey: queryKeys.goals.detail(id) });
      // The backend un-linked this goal's tasks.
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.byGoal(id) });
      toast.success("Goal deleted");
    },
  });
}

// ---------------------------------------------------------------- waiting to send

export type PendingKind = "send" | "delete";

/** Goal ids with a mutation paused by being offline (design-system.md §7.6). */
export function usePendingGoals(): Map<string, PendingKind> {
  const paused = useMutationState({
    filters: { mutationKey: ["goals"], predicate: (mutation) => mutation.state.isPaused },
    select: (mutation) => {
      const variables = mutation.state.variables as { id?: string; tempId?: string };
      const kind: PendingKind = mutation.options.mutationKey?.[1] === "delete" ? "delete" : "send";
      return [variables.id ?? variables.tempId ?? "", kind] as const;
    },
  });
  return new Map(paused);
}
