import { MessageCircleIcon } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = { title: "Chat · MyPA" };

// Placeholder until F1.2 (chat feed).
export default function ChatPage() {
  return (
    <EmptyState icon={MessageCircleIcon} title="Nothing yet.">
      Your briefings and questions will show up here. You can also just start typing.
    </EmptyState>
  );
}
