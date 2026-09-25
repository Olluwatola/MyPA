import { onlineManager, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OFFLINE_BANNER_DELAY_MS, OfflineBanner } from "@/components/offline-banner";
import { makeQueryClient } from "./query-config";

afterEach(() => {
  act(() => onlineManager.setOnline(true));
  vi.useRealTimers();
});

describe("offline banner", () => {
  it("appears only after the delay, and leaves when back online", () => {
    vi.useFakeTimers();
    render(<OfflineBanner />);

    act(() => onlineManager.setOnline(false));
    act(() => vi.advanceTimersByTime(OFFLINE_BANNER_DELAY_MS - 1));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("status")).toHaveTextContent("You're offline. Changes will send when you're back.");

    act(() => onlineManager.setOnline(true));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("doesn't show for a blip shorter than the delay", () => {
    vi.useFakeTimers();
    render(<OfflineBanner />);

    act(() => onlineManager.setOnline(false));
    act(() => vi.advanceTimersByTime(OFFLINE_BANNER_DELAY_MS / 2));
    act(() => onlineManager.setOnline(true));
    act(() => vi.advanceTimersByTime(OFFLINE_BANNER_DELAY_MS));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("mutations while offline", () => {
  it("are paused, not failed, and run once back online", async () => {
    const send = vi.fn().mockResolvedValue("sent");
    let mutation: ReturnType<typeof useMutation<string>> | undefined;
    function Sender() {
      mutation = useMutation({ mutationFn: send });
      return null;
    }
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <Sender />
      </QueryClientProvider>,
    );

    act(() => onlineManager.setOnline(false));
    act(() => mutation!.mutate());
    await vi.waitFor(() => expect(mutation!.isPaused).toBe(true));
    expect(send).not.toHaveBeenCalled();
    expect(mutation!.isError).toBe(false);

    act(() => onlineManager.setOnline(true));

    await vi.waitFor(() => expect(mutation!.isSuccess).toBe(true));
    expect(send).toHaveBeenCalledOnce();
  });
});
