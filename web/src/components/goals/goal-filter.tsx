"use client";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { VIEWS, type GoalView } from "@/lib/goals/labels";

export function GoalFilter({ view, onChange }: { view: GoalView; onChange: (view: GoalView) => void }) {
  return (
    <ToggleGroup
      type="single"
      value={view}
      // Radix sends "" when the active item is clicked again; keep the current view.
      onValueChange={(value) => value && onChange(value as GoalView)}
      aria-label="Show goals"
    >
      {(Object.keys(VIEWS) as GoalView[]).map((key) => (
        <ToggleGroupItem key={key} value={key}>
          {VIEWS[key].label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
