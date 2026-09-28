"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { SOURCE_LABEL, SOURCES, type Source } from "@/lib/sources";
import { STATUS_VIEWS, URGENCIES, URGENCY_LABEL, type StatusView, type TaskFilters, type Urgency } from "@/lib/tasks/labels";

type TaskFiltersProps = {
  filters: TaskFilters;
  onChange: (changes: Partial<TaskFilters>) => void;
};

/** Plan §1.3: Open | Done | All, plus Source and Urgency, plus Clear. Changes are instant. */
export function TaskFilterBar({ filters, onChange }: TaskFiltersProps) {
  const filtered = filters.source !== null || filters.urgency !== null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <ToggleGroup
        type="single"
        value={filters.status}
        // Radix sends "" when the active item is clicked again; keep the current view.
        onValueChange={(value) => value && onChange({ status: value as StatusView })}
        aria-label="Show tasks"
      >
        {(Object.keys(STATUS_VIEWS) as StatusView[]).map((key) => (
          <ToggleGroupItem key={key} value={key}>
            {STATUS_VIEWS[key].label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="flex items-center gap-2">
        <FilterSelect
          label="Source"
          value={filters.source}
          options={SOURCES.map((source) => [source, SOURCE_LABEL[source]])}
          onChange={(source) => onChange({ source: source as Source | null })}
        />
        <FilterSelect
          label="Urgency"
          value={filters.urgency}
          options={URGENCIES.map((urgency) => [urgency, URGENCY_LABEL[urgency]])}
          onChange={(urgency) => onChange({ urgency: urgency as Urgency | null })}
        />
        {filtered && (
          <button
            type="button"
            onClick={() => onChange({ source: null, urgency: null })}
            className="h-8 px-2 text-sm font-medium text-accent underline"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | null;
  options: [string, string][];
  onChange: (value: string | null) => void;
}) {
  const current = options.find(([key]) => key === value)?.[1] ?? "Any";
  return (
    <Select
      value={value ?? "any"}
      // Radix Select can report "" on its own; that's not a choice.
      onValueChange={(next) => next && onChange(next === "any" ? null : next)}
    >
      <SelectTrigger aria-label={`${label}: ${current}`} className="h-8 w-auto gap-1 text-sm pointer-coarse:h-10">
        <span className="text-ink-2">{label}:</span>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="any">Any</SelectItem>
        {options.map(([key, text]) => (
          <SelectItem key={key} value={key}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
