import { createCn } from "cn/config"

// The type scale in globals.css (design-system.md §4.2) adds font sizes Tailwind doesn't have.
// Without this, `cn` reads `text-title` as a text colour and drops it when `text-ink` follows.
export const cn = createCn({
  extend: { classGroups: { "font-size": [{ text: ["display", "title", "heading", "body"] }] } },
})
