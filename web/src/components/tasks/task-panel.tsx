"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { onlineManager, useQueryClient } from "@tanstack/react-query";
import { CalendarClockIcon, Loader2Icon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { DetailPanel } from "@/components/detail-panel";
import { RootError, useCloseGuard } from "@/components/panel-form";
import { PendingLabel } from "@/components/pending-label";
import { SourceBadge } from "@/components/source-badge";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-config";
import { useTimeZone } from "@/lib/auth/use-session";
import { formatAdded } from "@/lib/format/date";
import {
  EMPTY_TASK_FORM,
  taskFormSchema,
  toCreateBody,
  toFormValues,
  toPatchBody,
  type TaskFormInput,
  type TaskFormValues,
} from "@/lib/tasks/form-schema";
import type { Task } from "@/lib/tasks/labels";
import {
  PENDING_ID_PREFIX,
  useCreateTask,
  useDeleteTask,
  usePendingTasks,
  useTask,
  useUpdateTask,
} from "@/lib/tasks/queries";
import { DoneCheckbox } from "./done-checkbox";
import { TaskFields } from "./task-fields";
import { useTaskGuessing } from "./task-row";

const FORM_ID = "task-form";

type TaskPanelProps = {
  /** `"new"`, a task id, or `null` (closed) — mirrors the `?task=` URL param. */
  taskParam: string | null;
  onClose: () => void;
  /** After a create: close, and make sure the new task is visible (plan §6). */
  onCreated: (task: { urgency: TaskFormValues["urgency"] }) => void;
};

export function TaskPanel({ taskParam, onClose, onCreated }: TaskPanelProps) {
  if (taskParam === null) return null;
  if (taskParam === "new") return <CreateTaskPanel onClose={onClose} onCreated={onCreated} />;
  return <EditTaskPanel key={taskParam} id={taskParam} onClose={onClose} />;
}

function useTaskForm(values?: TaskFormInput) {
  return useForm<TaskFormInput, unknown, TaskFormValues>({
    resolver: zodResolver(taskFormSchema),
    defaultValues: EMPTY_TASK_FORM,
    values,
    // When the task refreshes underneath (AI guess arrives, ticked done), keep what the user is typing.
    resetOptions: { keepDirtyValues: true },
  });
}

function CreateTaskPanel({ onClose, onCreated }: Omit<TaskPanelProps, "taskParam">) {
  const form = useTaskForm();
  const create = useCreateTask();
  const guard = useCloseGuard(form.formState.isDirty, onClose, "task");

  const onSubmit = form.handleSubmit(async (values) => {
    const saving = create.mutateAsync({ body: toCreateBody(values), tempId: `${PENDING_ID_PREFIX}${crypto.randomUUID()}` });
    // Offline, the create waits for the connection; its row shows "Waiting to send" meanwhile.
    if (!onlineManager.isOnline()) {
      saving.catch(() => undefined);
      onCreated(values);
      return;
    }
    try {
      await saving;
      onCreated(values);
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
        title="New task"
        description="Add a task"
        footer={
          <>
            <Button type="submit" form={FORM_ID} disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting && <Loader2Icon aria-hidden className="animate-spin" />}
              Create task
            </Button>
            <Button variant="outline" onClick={guard.requestClose}>
              Cancel
            </Button>
          </>
        }
      >
        <Form {...form}>
          <form id={FORM_ID} onSubmit={onSubmit} noValidate>
            <TaskFields form={form} mode="create" />
            <RootError message={form.formState.errors.root?.message} />
          </form>
        </Form>
      </DetailPanel>
      {guard.dialog}
    </>
  );
}

function EditTaskPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const taskQuery = useTask(id);
  const task = taskQuery.data;
  const unavailable = taskQuery.error instanceof ApiError && [403, 404].includes(taskQuery.error.status);

  // Deleted elsewhere (or not this user's): the lists may still show it.
  useEffect(() => {
    if (unavailable) queryClient.invalidateQueries({ queryKey: queryKeys.tasks.lists });
  }, [unavailable, queryClient]);

  const values = useMemo(() => (task ? toFormValues(task) : undefined), [task]);
  const form = useTaskForm(values);
  const update = useUpdateTask();
  const guard = useCloseGuard(form.formState.isDirty, onClose, "task");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteTask = useDeleteTask();

  const onSubmit = form.handleSubmit((values) => {
    const body = toPatchBody(values, form.formState.dirtyFields);
    update.mutate(
      { id, body, previousGoalId: task?.goal_id ?? null },
      {
        onSuccess: (saved) => form.reset(toFormValues(saved)),
        onError: (error) => form.setError("root", { message: errorMessage(error) }),
      },
    );
  });

  if (unavailable || (taskQuery.isError && !task)) {
    return (
      <DetailPanel
        open
        onOpenChange={(open) => !open && onClose()}
        title="Task"
        description="This task can't be shown"
        footer={
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        }
      >
        <p className="text-ink-2">
          {unavailable ? "This task isn't available any more." : "Couldn't load this task. Check your connection and try again."}
        </p>
      </DetailPanel>
    );
  }

  return (
    <>
      <DetailPanel
        open
        onOpenChange={(open) => !open && guard.requestClose()}
        title={task?.title ?? "Task"}
        description="View and edit this task"
        footer={
          task && (
            <>
              <Button
                variant="ghost"
                className="mr-auto text-danger hover:bg-danger-soft"
                onClick={() => setConfirmingDelete(true)}
              >
                Delete task
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
        {task ? (
          <div className="flex flex-col gap-6">
            <TaskMeta task={task} />
            <Form {...form}>
              <form id={FORM_ID} onSubmit={onSubmit} noValidate>
                <EditFields task={task} form={form} />
                <RootError message={form.formState.errors.root?.message} />
              </form>
            </Form>
          </div>
        ) : (
          <div aria-busy="true" aria-label="Loading task" className="flex flex-col gap-4">
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
        title="Delete this task?"
        description="This can't be undone."
        confirmLabel="Delete task"
        onConfirm={() => {
          deleteTask.mutate({ id, goalId: task?.goal_id ?? null });
          onClose();
        }}
      />
    </>
  );
}

function EditFields({ task, form }: { task: Task; form: ReturnType<typeof useTaskForm> }) {
  const suggesting = useTaskGuessing(task);
  return (
    <TaskFields
      form={form}
      mode="edit"
      suggesting={suggesting}
      pinned={{
        title: task.title_manually_set,
        description: task.description_manually_set,
        urgency: task.urgency_manually_set,
        effort: task.effort_level_manually_set,
        goal: task.goal_id_manually_set,
      }}
    />
  );
}

/** Done, source, when it was added, a scheduled slot, and whether a change is waiting to send. */
function TaskMeta({ task }: { task: Task }) {
  const timeZone = useTimeZone();
  const pending = usePendingTasks().get(task.id);

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-ink-2">
      <span className="flex items-center gap-2">
        <DoneCheckbox task={task} />
        <span className={task.status === "done" ? "text-success" : undefined}>
          {task.status === "done" ? "Done" : "Open"}
        </span>
      </span>
      <SourceBadge source={task.source} />
      <span>{formatAdded(task.created_at, timeZone)}</span>
      {/* Only the event id is stored until Scouring (1.12) stores the slot itself (N-43). */}
      {task.scheduled_event_id && (
        <span className="inline-flex items-center gap-1">
          <CalendarClockIcon aria-hidden className="size-4" />
          Scheduled in your calendar
        </span>
      )}
      {pending && <PendingLabel kind={pending} />}
    </div>
  );
}
