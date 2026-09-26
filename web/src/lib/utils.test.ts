import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("keeps a custom font size next to a text colour", () => {
    expect(cn("font-serif text-title text-ink", "line-clamp-2")).toBe("font-serif text-title text-ink line-clamp-2");
  });

  it("still lets a later font size win", () => {
    expect(cn("text-sm", "text-title")).toBe("text-title");
  });
});
