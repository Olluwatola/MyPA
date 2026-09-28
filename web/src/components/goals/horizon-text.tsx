"use client";

import { SuggestingLabel, useGuessWindow } from "@/components/suggesting";
import { HORIZON_LABEL, type Goal } from "@/lib/goals/labels";

/** Whether the AI horizon guess can still arrive (goals plan §1.4). */
export function useIsGuessingHorizon(goal: Goal): boolean {
  const inWindow = useGuessWindow(goal.created_at);
  return goal.horizon == null && inWindow;
}

/** The goal's horizon as text, or "MyPA is suggesting…" while the AI guess can still arrive. */
export function HorizonText({ goal }: { goal: Goal }) {
  const guessing = useIsGuessingHorizon(goal);
  if (goal.horizon) return <>{HORIZON_LABEL[goal.horizon]}</>;
  if (guessing) return <SuggestingLabel />;
  return <>Not set</>;
}
