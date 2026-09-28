import { BrainIcon, FeatherIcon, HeadphonesIcon, type LucideIcon } from "lucide-react";

import { EFFORT_LABEL, URGENCY_LABEL, type EffortLevel, type Urgency } from "@/lib/tasks/labels";

// design-system.md §7.1: effort icons (the same ones Scouring will use).
const EFFORT_ICON: Record<EffortLevel, LucideIcon> = {
  deep_focus: BrainIcon,
  light_focus: FeatherIcon,
  passive: HeadphonesIcon,
};

export function EffortIcon({ effort }: { effort: EffortLevel }) {
  const Icon = EFFORT_ICON[effort];
  return <Icon role="img" aria-label={EFFORT_LABEL[effort]} className="size-4 shrink-0 text-ink-2" />;
}

/**
 * design-system.md §3.3: never colour alone — high is a filled red dot, medium an amber outline
 * dot, low (the quiet default) nothing. The label is always there for screen readers.
 */
export function UrgencyDot({ urgency }: { urgency: Urgency }) {
  if (urgency === "low") return null;
  return (
    <span
      role="img"
      aria-label={`${URGENCY_LABEL[urgency]} urgency`}
      className={
        urgency === "high"
          ? "size-2.5 shrink-0 rounded-full bg-danger"
          : "size-2.5 shrink-0 rounded-full border-[1.5px] border-warning"
      }
    />
  );
}
