"use client";

import { Loader2Icon, PlusIcon, TargetIcon } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { GoalView } from "@/lib/goals/labels";
import { useGoalsList, usePendingGoals } from "@/lib/goals/queries";
import { GoalRow } from "./goal-row";

const EMPTY: Record<GoalView, { title: string; body: string; action: boolean }> = {
  active: { title: "What are you working toward?", body: "Add a goal and MyPA will connect related tasks to it.", action: true },
  all: { title: "What are you working toward?", body: "Add a goal and MyPA will connect related tasks to it.", action: true },
  done: { title: "Nothing finished yet.", body: "Goals you mark done will show up here.", action: false },
  dropped: { title: "Nothing dropped.", body: "Goals you drop will show up here.", action: false },
};

export function GoalListSkeleton() {
  return (
    <ul aria-busy="true" aria-label="Loading goals">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i} className="flex min-h-14 items-center gap-4 border-b border-border px-3">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="hidden h-4 w-24 md:block" />
          <Skeleton className="h-6 w-16" />
        </li>
      ))}
    </ul>
  );
}

export function GoalList({ view, onOpen, onNew }: { view: GoalView; onOpen: (id: string) => void; onNew: () => void }) {
  const list = useGoalsList(view);
  const pending = usePendingGoals();

  if (list.isPending) return <GoalListSkeleton />;

  if (list.isError) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 px-4 py-16 text-center">
        <p className="text-ink-2">Couldn&apos;t load your goals. Check your connection and try again.</p>
        <Button variant="outline" onClick={() => list.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const goals = list.data.pages.flatMap((page) => page.data);
  if (goals.length === 0) {
    const empty = EMPTY[view];
    return (
      <div className="flex flex-col items-center pb-16">
        <EmptyState icon={TargetIcon} title={empty.title}>
          {empty.body}
        </EmptyState>
        {empty.action && (
          <Button onClick={onNew}>
            <PlusIcon aria-hidden />
            New goal
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <ul aria-label="Goals" className="border-t border-border">
        {goals.map((goal) => (
          <GoalRow key={goal.id} goal={goal} pending={pending.get(goal.id)} onOpen={onOpen} />
        ))}
      </ul>
      {list.hasNextPage && (
        <Button
          variant="outline"
          className="mx-auto mt-4"
          disabled={list.isFetchingNextPage}
          onClick={() => list.fetchNextPage()}
        >
          {list.isFetchingNextPage && <Loader2Icon aria-hidden className="animate-spin" />}
          Load more
        </Button>
      )}
    </div>
  );
}
