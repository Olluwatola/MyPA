"use client";

import { PlusIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { matchesFilters, parseTaskSearch, type Task, type TaskFilters } from "@/lib/tasks/labels";
import { usePanelFocusReturn, useSearchNavigate } from "@/lib/use-search-state";
import type { CalendarMode } from "./task-calendar";
import { TaskFilterBar } from "./task-filters";
import { TaskList } from "./task-list";
import { TaskPanel } from "./task-panel";

function CalendarSkeleton() {
  return <Skeleton aria-busy="true" aria-label="Loading calendar" className="h-128 w-full rounded-lg" />;
}

// FullCalendar only downloads when someone opens the Calendar view (decisions-log 2026-09-25).
const TaskCalendar = dynamic(() => import("./task-calendar"), { ssr: false, loading: CalendarSkeleton });

/**
 * The Tasks screen. The URL holds the view state (plan §1.8): list or calendar, filters, the
 * calendar range, and the open task. Back closes the panel.
 */
export function TasksView() {
  const search = parseTaskSearch(useSearchParams());
  const filters: TaskFilters = { status: search.status, source: search.source, urgency: search.urgency };
  const navigate = useSearchNavigate({ view: "list", status: "open", cal: "month" });
  const rememberOpener = usePanelFocusReturn(search.task);

  // Opening the panel adds a history entry so Back closes it; everything else replaces.
  const open = (task: string) => {
    rememberOpener();
    navigate({ task }, "push");
  };
  const close = () => navigate({ task: null }, "replace");
  const changeFilters = (changes: Partial<TaskFilters>) => navigate(changes, "replace");
  const clearFilters = () => navigate({ source: null, urgency: null }, "replace");

  // A new task is open, manual, and has the urgency picked (or Medium until guessed). If the
  // current filters would hide it, show Open with no filters.
  const created = ({ urgency }: { urgency: string }) => {
    const shape = { status: "open", source: "manual", urgency: urgency === "suggest" ? "medium" : urgency } as Task;
    navigate(
      matchesFilters(shape, filters) ? { task: null } : { task: null, status: "open", source: null, urgency: null },
      "replace",
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-4 md:py-8">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="hidden font-serif text-title font-medium md:block">Tasks</h1>
        <ToggleGroup
          type="single"
          value={search.view}
          onValueChange={(value) => value && navigate({ view: value }, "replace")}
          aria-label="Show tasks as"
          className="md:ml-4"
        >
          <ToggleGroupItem value="list">List</ToggleGroupItem>
          <ToggleGroupItem value="calendar">Calendar</ToggleGroupItem>
        </ToggleGroup>
        <Button className="ml-auto" onClick={() => open("new")}>
          <PlusIcon aria-hidden />
          New task
        </Button>
      </div>
      <TaskFilterBar filters={filters} onChange={changeFilters} />
      {search.view === "list" ? (
        <TaskList filters={filters} onOpen={open} onNew={() => open("new")} onClearFilters={clearFilters} />
      ) : (
        <TaskCalendar
          filters={filters}
          mode={search.cal}
          date={search.date}
          onOpen={open}
          onNavigate={(changes: { cal?: CalendarMode; date?: string }) => navigate(changes, "replace")}
        />
      )}
      <TaskPanel taskParam={search.task} onClose={close} onCreated={created} />
    </div>
  );
}
