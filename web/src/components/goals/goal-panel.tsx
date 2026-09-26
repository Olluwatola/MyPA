"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { onlineManager, useQueryClient } from "@tanstack/react-query";
import { CircleAlertIcon, Loader2Icon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { DetailPanel } from "@/components/detail-panel";
import { PendingLabel } from "@/components/pending-label";
import { SourceBadge } from "@/components/source-badge";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-config";
import { useTimeZone } from "@/lib/auth/use-session";
import { dayOf, formatDay } from "@/lib/format/date";
import {
  EMPTY_GOAL_FORM,
  goalFormSchema,
  toCreateBody,
  toFormValues,
  toPatchBody,
  type GoalFormInput,
  type GoalFormValues,
} from "@/lib/goals/form-schema";
import type { Goal } from "@/lib/goals/labels";
import {
  PENDING_ID_PREFIX,
  useCreateGoal,
  useDeleteGoal,
  useGoal,
  usePendingGoals,
  useUpdateGoal,
} from "@/lib/goals/queries";
import { GoalFields } from "./goal-fields";
import { GoalStatusMenu } from "./goal-status-menu";
import { useIsGuessingHorizon } from "./horizon-text";
import { LinkedTasks } from "./linked-tasks";

const FORM_ID = "goal-form";

type GoalPanelProps = {
  /** `"new"`, a goal id, or `null` (closed) — mirrors the `?goal=` URL param. */
  goalParam: string | null;
  onClose: () => void;
  /** After a create: close, and show a view the new (open) goal appears in. */
  onCreated: () => void;
};

export function GoalPanel({ goalParam, onClose, onCreated }: GoalPanelProps) {
  if (goalParam === null) return null;
  if (goalParam === "new") return <CreateGoalPanel onClose={onClose} onCreated={onCreated} />;
  return <EditGoalPanel key={goalParam} id={goalParam} onClose={onClose} />;
}

/** "Discard changes?" before closing a form with unsaved edits (plan §1.8). */
function useCloseGuard(isDirty: boolean, onClose: () => void) {
  const [confirming, setConfirming] = useState(false);
  return {
    requestClose: () => (isDirty ? setConfirming(true) : onClose()),
    dialog: (
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Discard changes?"
        description="Your edits to this goal haven't been saved."
        confirmLabel="Discard changes"
        cancelLabel="Keep editing"
        onConfirm={onClose}
      />
    ),
  };
}

function RootError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-4 flex items-center gap-1.5 text-sm text-danger">
      <CircleAlertIcon aria-hidden className="size-4 shrink-0" />
      {message}
    </p>
  );
}

function useGoalForm(values?: GoalFormInput) {
  return useForm<GoalFormInput, unknown, GoalFormValues>({
    resolver: zodResolver(goalFormSchema),
    defaultValues: EMPTY_GOAL_FORM,
    values,
    // When the goal refreshes underneath (AI horizon arrives, status changed), keep what the
    // user is typing.
    resetOptions: { keepDirtyValues: true },
  });
}

function CreateGoalPanel({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const form = useGoalForm();
  const create = useCreateGoal();
  const guard = useCloseGuard(form.formState.isDirty, onClose);

  const onSubmit = form.handleSubmit(async (values) => {
    const saving = create.mutateAsync({ body: toCreateBody(values), tempId: `${PENDING_ID_PREFIX}${crypto.randomUUID()}` });
    // Offline, the create waits for the connection; its row shows "Waiting to send" meanwhile.
    if (!onlineManager.isOnline()) {
      saving.catch(() => undefined);
      onCreated();
      return;
    }
    try {
      await saving;
      onCreated();
    } catch (error) {
      // Stay open with everything still filled in (never lose work).
      form.setError("root", { message: errorMessage(error) });
    }
  });

  return (
    <>
      <DetailPanel
        open
        onOpenChange={(open) => !open && guard.requestClose()}
        title="New goal"
        description="Add a goal"
        footer={
          <>
            <Button type="submit" form={FORM_ID} disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting && <Loader2Icon aria-hidden className="animate-spin" />}
              Create goal
            </Button>
            <Button variant="outline" onClick={guard.requestClose}>
              Cancel
            </Button>
          </>
        }
      >
        <Form {...form}>
          <form id={FORM_ID} onSubmit={onSubmit} noValidate>
            <GoalFields form={form} mode="create" />
            <RootError message={form.formState.errors.root?.message} />
          </form>
        </Form>
      </DetailPanel>
      {guard.dialog}
    </>
  );
}

function EditGoalPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const goalQuery = useGoal(id);
  const goal = goalQuery.data;
  const unavailable = goalQuery.error instanceof ApiError && [403, 404].includes(goalQuery.error.status);

  // Deleted elsewhere (or not this user's): the lists may still show it.
  useEffect(() => {
    if (unavailable) queryClient.invalidateQueries({ queryKey: queryKeys.goals.lists });
  }, [unavailable, queryClient]);

  const values = useMemo(() => (goal ? toFormValues(goal) : undefined), [goal]);
  const form = useGoalForm(values);
  const update = useUpdateGoal();
  const guard = useCloseGuard(form.formState.isDirty, onClose);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteGoal = useDeleteGoal();

  const onSubmit = form.handleSubmit((values) => {
    const body = toPatchBody(values, form.formState.dirtyFields);
    update.mutate(
      { id, body },
      {
        onSuccess: (saved) => form.reset(toFormValues(saved)),
        onError: (error) => form.setError("root", { message: errorMessage(error) }),
      },
    );
  });

  if (unavailable || (goalQuery.isError && !goal)) {
    return (
      <DetailPanel
        open
        onOpenChange={(open) => !open && onClose()}
        title="Goal"
        description="This goal can't be shown"
        footer={
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        }
      >
        <p className="text-ink-2">
          {unavailable ? "This goal isn't available any more." : "Couldn't load this goal. Check your connection and try again."}
        </p>
      </DetailPanel>
    );
  }

  return (
    <>
      <DetailPanel
        open
        onOpenChange={(open) => !open && guard.requestClose()}
        title={goal?.title ?? "Goal"}
        description="View and edit this goal"
        footer={
          goal && (
            <>
              <Button
                variant="ghost"
                className="mr-auto text-danger hover:bg-danger-soft"
                onClick={() => setConfirmingDelete(true)}
              >
                Delete goal
              </Button>
              <Button variant="outline" onClick={guard.requestClose}>
                Cancel
              </Button>
              <Button type="submit" form={FORM_ID} disabled={!form.formState.isDirty || update.isPending}>
                {update.isPending && !update.isPaused && <Loader2Icon aria-hidden className="animate-spin" />}
                Save
              </Button>
            </>
          )
        }
      >
        {goal ? (
          <div className="flex flex-col gap-6">
            <GoalMeta goal={goal} />
            <Form {...form}>
              <form id={FORM_ID} onSubmit={onSubmit} noValidate>
                <EditFields goal={goal} form={form} />
                <RootError message={form.formState.errors.root?.message} />
              </form>
            </Form>
            <LinkedTasks goalId={goal.id} />
          </div>
        ) : (
          <div aria-busy="true" aria-label="Loading goal" className="flex flex-col gap-4">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        )}
      </DetailPanel>
      {guard.dialog}
      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete this goal?"
        description="Its tasks stay, but lose the link."
        confirmLabel="Delete goal"
        onConfirm={() => {
          deleteGoal.mutate({ id });
          onClose();
        }}
      />
    </>
  );
}

function EditFields({ goal, form }: { goal: Goal; form: ReturnType<typeof useGoalForm> }) {
  const guessing = useIsGuessingHorizon(goal);
  return (
    <GoalFields
      form={form}
      mode="edit"
      titlePinned={goal.title_manually_set}
      descriptionPinned={goal.description_manually_set}
      suggestingHorizon={guessing}
    />
  );
}

/** Status, source, when it was added, and whether an offline change is waiting to send. */
function GoalMeta({ goal }: { goal: Goal }) {
  const timeZone = useTimeZone();
  const pending = usePendingGoals().get(goal.id);
  const added = formatDay(dayOf(goal.created_at, timeZone), timeZone);

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
      <GoalStatusMenu goal={goal} />
      <SourceBadge source={goal.source} />
      <span>Added {added === "Today" ? "today" : added}</span>
      {pending && <PendingLabel kind={pending} />}
    </div>
  );
}
