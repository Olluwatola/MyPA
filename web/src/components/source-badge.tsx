import { CalendarDaysIcon, FileTextIcon, MailIcon, MessageCircleIcon, PenLineIcon, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type Source = "manual" | "conversation" | "email" | "calendar" | "notion";

// design-system.md §3.3: low-chroma tints plus an icon and a word, so the source never relies on
// colour alone. Values live in globals.css (--badge-*).
const BADGES: Record<Source, { label: string; icon: LucideIcon; className: string }> = {
  manual: { label: "Manual", icon: PenLineIcon, className: "bg-badge-manual text-badge-manual-ink" },
  conversation: { label: "Chat", icon: MessageCircleIcon, className: "bg-badge-conversation text-badge-conversation-ink" },
  email: { label: "Email", icon: MailIcon, className: "bg-badge-email text-badge-email-ink" },
  calendar: { label: "Calendar", icon: CalendarDaysIcon, className: "bg-badge-calendar text-badge-calendar-ink" },
  notion: { label: "Notion", icon: FileTextIcon, className: "bg-badge-notion text-badge-notion-ink" },
};

export function SourceBadge({ source }: { source: Source }) {
  const { label, icon: Icon, className } = BADGES[source];
  return (
    <span
      className={cn("inline-flex h-6 items-center gap-1 rounded-sm px-1.5 text-xs font-medium whitespace-nowrap", className)}
    >
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}
