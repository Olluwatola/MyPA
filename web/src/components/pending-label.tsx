import { ClockIcon } from "lucide-react";

// design-system.md §7.6: an action taken offline stays on screen with this until it's sent.
export function PendingLabel({ kind = "send" }: { kind?: "send" | "delete" }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-ink-3">
      <ClockIcon aria-hidden className="size-3.5" />
      {kind === "send" ? "Waiting to send" : "Waiting to delete"}
    </span>
  );
}
