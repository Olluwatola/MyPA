import { CalendarDaysIcon, FileTextIcon, MailIcon, MessageCircleIcon, PenLineIcon, type LucideIcon } from "lucide-react";

import { SOURCE_LABEL, type Source } from "@/lib/sources";
import { cn } from "@/lib/utils";

export type { Source };

// design-system.md §3.3: low-chroma tints plus an icon and a word, so the source never relies on
// colour alone. Values live in globals.css (--badge-*).
const BADGES: Record<Source, { icon: LucideIcon; className: string }> = {
  manual: { icon: PenLineIcon, className: "bg-badge-manual text-badge-manual-ink" },
  conversation: { icon: MessageCircleIcon, className: "bg-badge-conversation text-badge-conversation-ink" },
  email: { icon: MailIcon, className: "bg-badge-email text-badge-email-ink" },
  calendar: { icon: CalendarDaysIcon, className: "bg-badge-calendar text-badge-calendar-ink" },
  notion: { icon: FileTextIcon, className: "bg-badge-notion text-badge-notion-ink" },
};

export function SourceBadge({ source }: { source: Source }) {
  const { icon: Icon, className } = BADGES[source];
  return (
    <span
      className={cn("inline-flex h-6 items-center gap-1 rounded-sm px-1.5 text-xs font-medium whitespace-nowrap", className)}
    >
      <Icon aria-hidden className="size-3.5" />
      {SOURCE_LABEL[source]}
    </span>
  );
}
