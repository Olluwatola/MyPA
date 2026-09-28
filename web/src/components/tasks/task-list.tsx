"use client";

import { CheckSquareIcon, Loader2Icon, PlusIcon } from "lucide-react";
import { useId } from "react";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTimeZone } from "@/lib/auth/use-session";
import { todayIn } from "@/lib/format/date";
import { useGoalTitles } from "@/lib/goals/queries";
import { DUE_GROUP_LABEL, groupTasks, type DueGroup } from "@/lib/tasks/due-groups";
import { matchesFilters, type Task, type TaskFilters } from "@/lib/tasks/labels";
import { usePendingTasks, useTasksList } from "@/lib/tasks/queries";
import { cn } from "@/lib/utils";
import { TaskRow } from "./task-row";

export function TaskListSkeleton() {
  return (
    <ul aria-busy="true" aria-label="Loading tasks">
      {Array.from({ length: 6 }, (_, i) => (
        <li key={i} className="flex min-h-14 items-center gap-4 border-b border-border px-3">
          <Skeleton className="size-5 rounded-full" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="hidden h-4 w-20 md:block" />
          <Skeleton className="h-6 w-16" />
        </li>
      ))}
    </ul>
  );
}

type TaskListProps = {
  filters: TaskFilters;
  onOpen: (id: string) => void;
  onNew: () => void;
  onClearFilters: () => void;
};

export function TaskList({ filters, onOpen, onNew, onClearFilters }: TaskListProps) {
  const list = useTasksList(filters);
  const pending = usePendingTasks();
  const goals = useGoalTitles().data;
  const timeZone = useTimeZone();

  if (list.isPending) return <TaskListSkeleton />;

  if (list.isError) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 px-4 py-16 text-center">
        <p className="text-ink-2">Couldn&apos;t load your tasks. Check your connection and try again.</p>
        <Button variant="outline" onClick={() => list.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const tasks = list.data.pages.flatMap((page) => page.data);
  if (tasks.length === 0) {
    return <EmptyTasks filters={filters} onNew={onNew} onClearFilters={onClearFilters} />;
  }

  const row = (task: Task) => (
    <TaskRow
      key={task.id}
      task={task}
      goal={task.goal_id ? goals?.get(task.goal_id) : undefined}
      pending={pending.get(task.id)}
      leaving={!matchesFilters(task, filters)}
      onOpen={onOpen}
    />
  );

  return (
    <div className="flex flex-col">
      {filters.status === "open" ? (
        <div className="border-t border-border">
          {groupTasks(tasks, todayIn(timeZone)).map(({ group, tasks: grouped }) => (
            <DueGroupSection key={group} group={group}>
              {grouped.map(row)}
            </DueGroupSection>
          ))}
        </div>
      ) : (
        <ul aria-label="Tasks" className="border-t border-border">
          {tasks.map(row)}
        </ul>
      )}
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

/** Plan §1.4: a heading per due group, kept in view while its tasks scroll under it. */
function DueGroupSection({ group, children }: { group: DueGroup; children: React.ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h3
        id={id}
        className={cn(
          "sticky top-0 z-10 border-b border-border bg-canvas px-2 py-1.5 text-xs font-medium tracking-label text-ink-2 uppercase md:top-(--tab-bar-height) md:px-3",
          group === "overdue" && "text-danger",
        )}
      >
        {DUE_GROUP_LABEL[group]}
      </h3>
      <ul aria-labelledby={id}>{children}</ul>
    </section>
  );
}

function EmptyTasks({ filters, onNew, onClearFilters }: Omit<TaskListProps, "onOpen">) {
  if (filters.source !== null || filters.urgency !== null) {
    return (
      <div className="flex flex-col items-center pb-16">
        <EmptyState icon={CheckSquareIcon} title="No tasks match these filters.">
          Try a different source or urgency.
        </EmptyState>
        <Button variant="outline" onClick={onClearFilters}>
          Clear filters
        </Button>
      </div>
    );
  }
  if (filters.status === "done") {
    return (
      <EmptyState icon={CheckSquareIcon} title="Nothing finished yet.">
        Tasks you tick off will show up here.
      </EmptyState>
    );
  }
  return (
    <div className="flex flex-col items-center pb-16">
      <EmptyState icon={CheckSquareIcon} title="A clear list.">
        Tasks from your email, calendar and chats will appear here, or add one yourself.
      </EmptyState>
      <Button onClick={onNew}>
        <PlusIcon aria-hidden />
        New task
      </Button>
    </div>
  );
}
