"use client";

import { CircleAlertIcon } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";

/** "Discard changes?" before closing a panel form with unsaved edits (goals plan §1.8). */
export function useCloseGuard(isDirty: boolean, onClose: () => void, item: "goal" | "task") {
  const [confirming, setConfirming] = useState(false);
  return {
    requestClose: () => (isDirty ? setConfirming(true) : onClose()),
    dialog: (
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Discard changes?"
        description={`Your edits to this ${item} haven't been saved.`}
        confirmLabel="Discard changes"
        cancelLabel="Keep editing"
        onConfirm={onClose}
      />
    ),
  };
}

/** A server refusal, shown inline above the panel footer with the form still filled in. */
export function RootError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-4 flex items-center gap-1.5 text-sm text-danger">
      <CircleAlertIcon aria-hidden className="size-4 shrink-0" />
      {message}
    </p>
  );
}
