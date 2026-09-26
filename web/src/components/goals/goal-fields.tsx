"use client";

import { PinIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { UseFormReturn } from "react-hook-form";

import { FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { GoalFormInput, GoalFormValues } from "@/lib/goals/form-schema";
import { SuggestingHorizon } from "./horizon-text";

const PIN_TEXT = "You set this — the assistant won't change it";

/** design-system.md §7.3: marks a field the user edited by hand (a sticky override). */
function ManualPin() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={PIN_TEXT}
          className="flex size-6 items-center justify-center rounded-sm text-ink-3 hover:text-ink-2"
        >
          <PinIcon aria-hidden className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>{PIN_TEXT}</TooltipContent>
    </Tooltip>
  );
}

function LabelRow({ children, pinned }: { children: ReactNode; pinned?: boolean }) {
  return (
    <div className="flex items-center gap-1">
      {children}
      {pinned && <ManualPin />}
    </div>
  );
}

type GoalFieldsProps = {
  form: UseFormReturn<GoalFormInput, unknown, GoalFormValues>;
  mode: "create" | "edit";
  titlePinned?: boolean;
  descriptionPinned?: boolean;
  /** Shows "MyPA is suggesting…" instead of the horizon picker while the AI guess can arrive. */
  suggestingHorizon?: boolean;
};

export function GoalFields({ form, mode, titlePinned, descriptionPinned, suggestingHorizon }: GoalFieldsProps) {
  return (
    <div className="flex flex-col gap-4">
      <FormField
        control={form.control}
        name="title"
        render={({ field }) => (
          <FormItem>
            <LabelRow pinned={titlePinned}>
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
            <LabelRow pinned={descriptionPinned}>
              <FormLabel>Description</FormLabel>
            </LabelRow>
            <FormControl>
              <Textarea rows={3} {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      {suggestingHorizon ? (
        <div className="grid gap-2">
          <p className="text-sm font-medium">Horizon</p>
          <p className="text-sm text-ink-2">
            <SuggestingHorizon />
          </p>
        </div>
      ) : (
        <FormField
          control={form.control}
          name="horizon"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Horizon</FormLabel>
              {/* Radix Select reports "" when the form's values arrive after mount; that isn't a
                  choice the user made, and would leave the field invalid (Save silently refused). */}
              <Select value={field.value} onValueChange={(value) => value && field.onChange(value)}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value="unset">{mode === "create" ? "Let MyPA suggest" : "Not set"}</SelectItem>
                  <SelectItem value="short_term">Short-term</SelectItem>
                  <SelectItem value="long_term">Long-term</SelectItem>
                </SelectContent>
              </Select>
              {mode === "create" && (
                <FormDescription>MyPA guesses this from the title if you leave it.</FormDescription>
              )}
              <FormMessage />
            </FormItem>
          )}
        />
      )}
      <FormField
        control={form.control}
        name="targetDate"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Target date</FormLabel>
            <FormControl>
              <Input type="date" {...field} />
            </FormControl>
            <FormDescription>Optional</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
    </div>
  );
}
