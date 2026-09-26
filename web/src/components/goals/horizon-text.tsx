"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useState } from "react";

import { HORIZON_LABEL, type Goal } from "@/lib/goals/labels";
import { HORIZON_GUESS_WINDOW_MS, isGuessingHorizon } from "@/lib/goals/queries";

/**
 * Whether the AI horizon guess can still arrive (§1.4). Re-renders by itself when the window ends:
 * the list's re-checks may come back unchanged (304), which wouldn't re-render anything.
 */
export function useIsGuessingHorizon(goal: Goal): boolean {
  const [now, setNow] = useState(() => Date.now());
  const guessing = isGuessingHorizon(goal, now);

  useEffect(() => {
    if (!guessing) return;
    const endsAt = new Date(goal.created_at).getTime() + HORIZON_GUESS_WINDOW_MS;
    const timer = setTimeout(() => setNow(Date.now()), Math.max(endsAt - Date.now(), 0));
    return () => clearTimeout(timer);
  }, [guessing, goal.created_at]);

  return guessing;
}

export function SuggestingHorizon() {
  return (
    <span className="inline-flex items-center gap-1">
      <Loader2Icon aria-hidden className="size-3.5 animate-spin" />
      MyPA is suggesting…
    </span>
  );
}

/** The goal's horizon as text, or "MyPA is suggesting…" while the AI guess can still arrive. */
export function HorizonText({ goal }: { goal: Goal }) {
  const guessing = useIsGuessingHorizon(goal);
  if (goal.horizon) return <>{HORIZON_LABEL[goal.horizon]}</>;
  if (guessing) return <SuggestingHorizon />;
  return <>Not set</>;
}
