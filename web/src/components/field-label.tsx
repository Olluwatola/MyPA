"use client";

import { PinIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const PIN_TEXT = "You set this — the assistant won't change it";

/** design-system.md §7.3: marks a field the user edited by hand (a sticky override). */
export function ManualPin() {
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

/** A field label with the pin beside it (outside the `<label>`, so clicking the pin isn't a label click). */
export function LabelRow({ children, pinned }: { children: ReactNode; pinned?: boolean }) {
  return (
    <div className="flex items-center gap-1">
      {children}
      {pinned && <ManualPin />}
    </div>
  );
}
