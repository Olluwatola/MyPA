import { TargetIcon } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = { title: "Goals · MyPA" };

// Placeholder until F1.6 (goals view).
export default function GoalsPage() {
  return (
    <EmptyState icon={TargetIcon} title="What are you working toward?">
      Your goals will show up here, with the tasks MyPA connects to them.
    </EmptyState>
  );
}
