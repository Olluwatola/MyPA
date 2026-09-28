"use client";

import type { UseFormReturn } from "react-hook-form";

import { LabelRow } from "@/components/field-label";
import { SuggestingLabel } from "@/components/suggesting";
import { FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useTimeZone } from "@/lib/auth/use-session";
import { addDays, todayIn } from "@/lib/format/date";
import { STATUS_LABEL } from "@/lib/goals/labels";
import { useGoalTitles } from "@/lib/goals/queries";
import { EFFORT_LABEL, EFFORTS, URGENCIES, URGENCY_LABEL } from "@/lib/tasks/labels";
import type { TaskFormInput, TaskFormValues } from "@/lib/tasks/form-schema";

type Form = UseFormReturn<TaskFormInput, unknown, TaskFormValues>;

type TaskFieldsProps = {
  form: Form;
  mode: "create" | "edit";
  /** Which fields the user set by hand (sticky), shown with a pin. */
  pinned?: { title?: boolean; description?: boolean; urgency?: boolean; effort?: boolean; goal?: boolean };
  /** Shows "MyPA is suggesting…" instead of the picker while the AI guess can arrive. */
  suggesting?: { urgency: boolean; effort: boolean };
};

export function TaskFields({ form, mode, pinned = {}, suggesting }: TaskFieldsProps) {
  return (
    <div className="flex flex-col gap-4">
      <FormField
        control={form.control}
        name="title"
        render={({ field }) => (
          <FormItem>
            <LabelRow pinned={pinned.title}>
              <FormLabel>Title</FormLabel>
            </LabelRow>
            <FormControl>
              <Input autoComplete="off" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="description"
        render={({ field }) => (
          <FormItem>
            <LabelRow pinned={pinned.description}>
              <FormLabel>Description</FormLabel>
            </LabelRow>
            <FormControl>
              <Textarea rows={3} {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <DueDateField form={form} />
      <div className="grid gap-4 sm:grid-cols-2">
        {suggesting?.urgency ? (
          <SuggestingField label="Urgency" />
        ) : (
          <PickerField
            form={form}
            name="urgency"
            label="Urgency"
            pinned={pinned.urgency}
            options={[
              ...(mode === "create" ? ([["suggest", "Let MyPA suggest"]] as [string, string][]) : []),
              ...URGENCIES.map((urgency): [string, string] => [urgency, URGENCY_LABEL[urgency]]),
            ]}
          />
        )}
        {suggesting?.effort ? (
          <SuggestingField label="Effort" />
        ) : (
          <PickerField
            form={form}
            name="effort"
            label="Effort"
            pinned={pinned.effort}
            options={[
              mode === "create" ? ["suggest", "Let MyPA suggest"] : ["none", "Not set"],
              ...EFFORTS.map((effort): [string, string] => [effort, EFFORT_LABEL[effort]]),
            ]}
          />
        )}
      </div>
      {mode === "create" && (
        <p className="-mt-2 text-sm text-ink-2">MyPA guesses urgency and effort from the title if you leave them.</p>
      )}
      <GoalField form={form} pinned={pinned.goal} />
    </div>
  );
}

function SuggestingField({ label }: { label: string }) {
  return (
    <div className="grid gap-2">
      <p className="text-sm font-medium">{label}</p>
      <p className="flex h-10 items-center text-sm text-ink-2">
        <SuggestingLabel />
      </p>
    </div>
  );
}

function PickerField({
  form,
  name,
  label,
  pinned,
  options,
}: {
  form: Form;
  name: "urgency" | "effort" | "goalId";
  label: string;
  pinned?: boolean;
  options: [string, string][];
}) {
  return (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <LabelRow pinned={pinned}>
            <FormLabel>{label}</FormLabel>
          </LabelRow>
          {/* Radix Select reports "" when the form's values arrive after mount; not a choice. */}
          <Select value={field.value} onValueChange={(value) => value && field.onChange(value)}>
            <FormControl>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              {options.map(([value, text]) => (
                <SelectItem key={value} value={value}>
                  {text}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

/**
 * Native date input plus quick chips (plan §1.8, instead of typed dates like "next friday"): the
 * native picker is accessible, gives phones their own picker, and adds nothing to the bundle.
 */
function DueDateField({ form }: { form: Form }) {
  const timeZone = useTimeZone();
  const today = todayIn(timeZone);
  const chips: [string, string][] = [
    ["Today", today],
    ["Tomorrow", addDays(today, 1)],
    ["Next week", addDays(today, 7)],
  ];

  return (
    <FormField
      control={form.control}
      name="dueDate"
      render={({ field }) => (
        <FormItem>
          <FormLabel>Due date</FormLabel>
          <FormControl>
            <Input type="date" {...field} />
          </FormControl>
          <div className="flex flex-wrap gap-2">
            {chips.map(([label, date]) => (
              <button
                key={label}
                type="button"
                aria-pressed={field.value === date}
                onClick={() => form.setValue("dueDate", date, { shouldDirty: true })}
                className="h-8 rounded-full border border-border-strong px-3 text-sm text-ink hover:bg-muted aria-pressed:border-accent aria-pressed:bg-accent-soft aria-pressed:text-accent-ink pointer-coarse:h-10"
              >
                {label}
              </button>
            ))}
          </div>
          <FormDescription>Optional</FormDescription>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

/**
 * Plan §1.6: open and paused goals, plus "No goal". A task linked to a done or dropped goal keeps
 * that goal as its current value ("Launch v1 · Done").
 */
function GoalField({ form, pinned }: { form: Form; pinned?: boolean }) {
  const goals = useGoalTitles().data;
  const current = form.watch("goalId");
  const options: [string, string][] = [["none", "No goal"]];
  for (const [id, goal] of goals ?? []) {
    if (goal.status === "open" || goal.status === "paused") options.push([id, goal.title]);
    else if (id === current) options.push([id, `${goal.title} · ${STATUS_LABEL[goal.status]}`]);
  }

  return <PickerField form={form} name="goalId" label="Goal" pinned={pinned} options={options} />;
}
