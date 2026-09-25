import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

// design-system.md §7.6: one serif line, one plain sentence, at most one action. No illustrations.
export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-sm flex-1 flex-col items-center justify-center gap-3 px-4 py-16 text-center">
      <Icon aria-hidden className="size-8 text-ink-3" />
      <h2 className="font-serif text-display font-medium text-ink">{title}</h2>
      <p className="text-ink-2">{children}</p>
    </div>
  );
}
