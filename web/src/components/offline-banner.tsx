"use client";

import { WifiOffIcon } from "lucide-react";

import { useIsOfflineFor } from "@/lib/api/offline";

export const OFFLINE_BANNER_DELAY_MS = 3000;

// design-system.md §7.6: same slot and timing as the "Reconnecting…" banner (PRD §7).
export function OfflineBanner() {
  const visible = useIsOfflineFor(OFFLINE_BANNER_DELAY_MS);

  if (!visible) return null;

  return (
    <div
      role="status"
      className="fixed inset-x-0 top-2 z-50 flex justify-center px-4 duration-(--dur-small) ease-out motion-safe:animate-in motion-safe:slide-in-from-top-2 motion-reduce:animate-in motion-reduce:fade-in"
    >
      <p className="flex items-center gap-2 rounded-lg bg-warning-soft px-4 py-2 text-sm font-medium text-warning shadow-2">
        <WifiOffIcon aria-hidden className="size-4" />
        You&apos;re offline. Changes will send when you&apos;re back.
      </p>
    </div>
  );
}
