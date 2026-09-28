"use client";

import type { UseFormReturn } from "react-hook-form";

import { LabelRow } from "@/components/field-label";
import { SuggestingLabel } from "@/components/suggesting";
import { FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { GoalFormInput, GoalFormValues } from "@/lib/goals/form-schema";

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
            <SuggestingLabel />
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
