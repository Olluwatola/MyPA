import type { ReactNode } from "react";

import { TabBar } from "@/components/tab-bar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <TabBar />
      <main className="flex flex-1 flex-col pb-tab-bar md:pb-0">{children}</main>
    </div>
  );
}
