"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useState } from "react";

import { GUESS_WINDOW_MS, isInGuessWindow } from "@/lib/guess-window";

/**
 * Whether an item is still inside its AI-guess window. Re-renders by itself when the window ends:
 * the re-checks may come back unchanged (304), which wouldn't re-render anything.
 */
export function useGuessWindow(createdAt: string): boolean {
  const [now, setNow] = useState(() => Date.now());
  const inWindow = isInGuessWindow(createdAt, now);

  useEffect(() => {
    if (!inWindow) return;
    const endsAt = new Date(createdAt).getTime() + GUESS_WINDOW_MS;
    const timer = setTimeout(() => setNow(Date.now()), Math.max(endsAt - Date.now(), 0));
    return () => clearTimeout(timer);
  }, [inWindow, createdAt]);

  return inWindow;
}

export function SuggestingLabel() {
  return (
    <span className="inline-flex items-center gap-1">
      <Loader2Icon aria-hidden className="size-3.5 animate-spin" />
      MyPA is suggesting…
    </span>
  );
}
