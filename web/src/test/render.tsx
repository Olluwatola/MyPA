import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/api/query-config";
import { AuthProvider } from "@/lib/auth/auth-provider";

/** Renders `ui` inside the same providers as the app, in StrictMode like `next dev`. */
export function renderWithProviders(ui: ReactNode) {
  const queryClient = makeQueryClient();
  const result = render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{ui}</AuthProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
  return { ...result, queryClient };
}
