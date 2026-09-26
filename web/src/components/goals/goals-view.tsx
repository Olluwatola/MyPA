"use client";

import { PlusIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { parseView, type GoalView } from "@/lib/goals/labels";
import { GoalFilter } from "./goal-filter";
import { GoalList } from "./goal-list";
import { GoalPanel } from "./goal-panel";

/**
 * The Goals screen. The URL holds the view state (`?status=done&goal=<id>`, plan §1.8): a reload
 * keeps the filter and the open goal, and Back closes the panel.
 */
export function GoalsView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const view = parseView(searchParams.get("status"));
  const goalParam = searchParams.get("goal");

  function navigate(changes: Record<string, string | null>, mode: "push" | "replace") {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) params.delete(key);
      else params.set(key, value);
    }
    if (params.get("status") === "active") params.delete("status");
    const query = params.toString();
    router[mode](query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  // The panel unmounts when closed, so Radix can't return focus itself: put it back on whatever
  // opened the panel (a row, "New goal"), however it was closed — X, Esc, Cancel or Back.
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (goalParam === null && opener.current?.isConnected) opener.current.focus();
    if (goalParam === null) opener.current = null;
  }, [goalParam]);

  // Opening the panel adds a history entry so Back closes it; everything else replaces.
  const open = (goal: string) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    navigate({ goal }, "push");
  };
  const close = () => navigate({ goal: null }, "replace");
  const changeView = (next: GoalView) => navigate({ status: next }, "replace");
  // A new goal is open: from Done/Dropped, switch to Active so it's visible.
  const created = () => navigate({ goal: null, status: view === "done" || view === "dropped" ? "active" : view }, "replace");

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-4 md:py-8">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="hidden font-serif text-title font-medium md:block">Goals</h1>
        <div className="order-last w-full overflow-x-auto sm:order-none sm:w-auto md:ml-4">
          <GoalFilter view={view} onChange={changeView} />
        </div>
        <Button className="ml-auto" onClick={() => open("new")}>
          <PlusIcon aria-hidden />
          New goal
        </Button>
      </div>
      <GoalList view={view} onOpen={open} onNew={() => open("new")} />
      <GoalPanel goalParam={goalParam} onClose={close} onCreated={created} />
    </div>
  );
}
