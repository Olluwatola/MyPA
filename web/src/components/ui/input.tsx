import * as React from "react"
import { cn } from "cn"

// design-system.md §7.4. Always 16px text: below that iOS Safari zooms in on focus (§4.2).
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-10 w-full min-w-0 rounded-md border border-border-strong bg-surface px-3 text-body text-ink outline-offset-0 placeholder:text-ink-3 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:h-11",
        "aria-invalid:border-danger",
        className
      )}
      {...props}
    />
  )
}

export { Input }
