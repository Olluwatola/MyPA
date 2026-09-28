"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Changes the page's query string. `defaults` are left out of the URL (e.g. `status=active`), so
 * the default view has a clean address. `push` adds a history entry (opening a panel, so Back
 * closes it); `replace` doesn't (filters, closing).
 */
export function useSearchNavigate(defaults: Record<string, string> = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (changes: Record<string, string | null>, mode: "push" | "replace") => {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) params.delete(key);
      else params.set(key, value);
    }
    for (const [key, value] of Object.entries(defaults)) {
      if (params.get(key) === value) params.delete(key);
    }
    const query = params.toString();
    router[mode](query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
}

/**
 * A detail panel unmounts when closed, so Radix can't return focus itself. Call `remember()` when
 * opening; focus goes back to that element however the panel closes — X, Esc, Cancel or Back.
 */
export function usePanelFocusReturn(panelParam: string | null) {
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (panelParam === null && opener.current?.isConnected) opener.current.focus();
    if (panelParam === null) opener.current = null;
  }, [panelParam]);

  return () => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  };
}
