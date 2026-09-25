"use client";

import { Loader2Icon, LogOutIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/use-session";

export function LogoutButton() {
  const { logout } = useAuth();
  const [pending, setPending] = useState(false);

  return (
    <Button
      variant="outline"
      disabled={pending}
      onClick={async () => {
        setPending(true);
        await logout();
      }}
    >
      {pending ? <Loader2Icon aria-hidden className="animate-spin" /> : <LogOutIcon aria-hidden />}
      Log out
    </Button>
  );
}
