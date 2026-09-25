import type { Metadata } from "next";

import { LogoutButton } from "@/components/logout-button";

export const metadata: Metadata = { title: "Settings · MyPA" };

// Only "Log out" until F1.7 (settings).
export default function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <h1 className="font-serif text-title font-medium">Settings</h1>
      <section aria-labelledby="account-heading" className="flex flex-col items-start gap-3">
        <h2 id="account-heading" className="text-heading font-semibold">
          Account
        </h2>
        <LogoutButton />
      </section>
    </div>
  );
}
