import { vi } from "vitest";

/** State behind the `next/navigation` mock (setup.ts). Tests set `pathname`/`search`, read `replace`. */
export const navigation = {
  pathname: "/chat",
  search: "",
  replace: vi.fn(),
};

export function resetNavigation() {
  navigation.pathname = "/chat";
  navigation.search = "";
  navigation.replace = vi.fn();
}
