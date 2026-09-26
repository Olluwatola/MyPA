import { vi } from "vitest";

/**
 * State behind the `next/navigation` mock (setup.ts). Tests set `pathname`/`search` and read
 * `replace`/`push`, which also change the URL and re-render whatever reads it.
 */
export const navigation = {
  pathname: "/chat",
  search: "",
  replace: vi.fn(setUrl),
  push: vi.fn(setUrl),
};

const listeners = new Set<() => void>();

function setUrl(url: string) {
  const parsed = new URL(url, "http://localhost:3000");
  navigation.pathname = parsed.pathname;
  navigation.search = parsed.search.slice(1);
  listeners.forEach((listener) => listener());
}

export function subscribeToNavigation(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function resetNavigation() {
  navigation.pathname = "/chat";
  navigation.search = "";
  navigation.replace = vi.fn(setUrl);
  navigation.push = vi.fn(setUrl);
}
