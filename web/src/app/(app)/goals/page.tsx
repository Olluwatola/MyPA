import type { Metadata } from "next";
import { Suspense } from "react";

import { GoalListSkeleton } from "@/components/goals/goal-list";
import { GoalsView } from "@/components/goals/goals-view";

export const metadata: Metadata = { title: "Goals · MyPA" };

// Suspense because the view reads its filter and open goal from the URL.
export default function GoalsPage() {
  return (
    <Suspense fallback={<GoalListSkeleton />}>
      <GoalsView />
    </Suspense>
  );
}
