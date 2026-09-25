import { onlineManager } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

/** Offline as TanStack Query sees it — the same signal that pauses queries and mutations. */
export function useIsOffline(): boolean {
  return useSyncExternalStore(
    (onChange) => onlineManager.subscribe(onChange),
    () => !onlineManager.isOnline(),
    () => false,
  );
}

/** Offline for at least `delayMs` — so a short blip doesn't flash a banner (PRD §7). */
export function useIsOfflineFor(delayMs: number): boolean {
  const offline = useIsOffline();
  const [elapsed, setElapsed] = useState(false);

  useEffect(() => {
    if (!offline) return;
    const timer = setTimeout(() => setElapsed(true), delayMs);
    return () => {
      clearTimeout(timer);
      setElapsed(false);
    };
  }, [offline, delayMs]);

  return offline && elapsed;
}
