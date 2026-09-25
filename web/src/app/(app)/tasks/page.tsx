import { CheckSquareIcon } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = { title: "Tasks · MyPA" };

// Placeholder until F1.5 (tasks view).
export default function TasksPage() {
  return (
    <EmptyState icon={CheckSquareIcon} title="A clear list.">
      Tasks from your email, calendar and chats will appear here.
    </EmptyState>
  );
}
