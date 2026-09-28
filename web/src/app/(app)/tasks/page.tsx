import type { Metadata } from "next";
import { Suspense } from "react";

import { TaskListSkeleton } from "@/components/tasks/task-list";
import { TasksView } from "@/components/tasks/tasks-view";

export const metadata: Metadata = { title: "Tasks · MyPA" };

// Suspense because the view reads its filters and open task from the URL.
export default function TasksPage() {
  return (
    <Suspense fallback={<TaskListSkeleton />}>
      <TasksView />
    </Suspense>
  );
}
