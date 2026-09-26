"use client";

import { CheckSquareIcon, MessageCircleIcon, SettingsIcon, TargetIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

type Tab = { href: string; label: string; icon: LucideIcon };

// PRD §4: the same four destinations at every width.
const TABS: Tab[] = [
  { href: "/chat", label: "Chat", icon: MessageCircleIcon },
  { href: "/tasks", label: "Tasks", icon: CheckSquareIcon },
  { href: "/goals", label: "Goals", icon: TargetIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
];

/**
 * design-system.md §7.2. Below 768px: fixed bottom bar, icon over label. From 768px: slim top bar,
 * wordmark left, tabs right. Tab switches never animate (used many times a day, §6.2).
 */
export function TabBar() {
  const pathname = usePathname();

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] shadow-1 md:sticky md:top-0 md:bottom-auto md:border-t-0 md:border-b md:pb-0 md:shadow-none">
      <div className="mx-auto flex h-(--tab-bar-height) max-w-5xl items-center md:px-6">
        <Link href="/chat" className="hidden font-serif text-title font-medium text-ink md:block">
          MyPA
        </Link>
        <nav aria-label="Main" className="h-full flex-1 md:ml-auto md:flex-none">
          <ul className="grid h-full grid-cols-4 md:flex md:gap-2">
            {TABS.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <li key={href} className="h-full">
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group flex h-full flex-col items-center justify-center gap-0.5 text-xs font-medium text-ink-2",
                      "md:flex-row md:gap-2 md:border-b-2 md:border-transparent md:px-3 md:pt-0.5 md:text-sm",
                      "aria-[current=page]:text-accent md:aria-[current=page]:border-accent",
                    )}
                  >
                    <span className="flex h-7 w-12 items-center justify-center rounded-full group-aria-[current=page]:bg-accent-soft md:h-auto md:w-auto md:bg-transparent md:group-aria-[current=page]:bg-transparent">
                      <Icon aria-hidden className="size-5 md:size-4" />
                    </span>
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </div>
  );
}
