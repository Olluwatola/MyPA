import * as React from "react"
import { cn } from "@/lib/utils"

// Matches Input (design-system.md §7.4). Grows with its content; always 16px text (§4.2).
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-20 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-body text-ink outline-offset-0 placeholder:text-ink-3 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
