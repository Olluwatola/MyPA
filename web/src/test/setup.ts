import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { setAccessToken } from "@/lib/auth/session";
import { navigation, resetNavigation, subscribeToNavigation } from "./navigation-mock";
import { calls, server } from "./server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: (url: string) => navigation.replace(url),
    push: (url: string) => navigation.push(url),
    prefetch: vi.fn(),
  }),
  usePathname: () => useSyncExternalStore(subscribeToNavigation, () => navigation.pathname),
  useSearchParams: () =>
    new URLSearchParams(useSyncExternalStore(subscribeToNavigation, () => navigation.search)),
}));

// jsdom gaps that Radix (Select, DropdownMenu, popper positioning) and useMediaQuery rely on.
// Tests render the desktop layout (the side sheet).
window.matchMedia = (query: string) =>
  ({
    matches: query.includes("min-width: 768px"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;
window.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => undefined;
Element.prototype.releasePointerCapture = () => undefined;
Element.prototype.scrollIntoView = () => undefined;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  calls.clear();
  setAccessToken(null);
  resetNavigation();
});
afterAll(() => server.close());
