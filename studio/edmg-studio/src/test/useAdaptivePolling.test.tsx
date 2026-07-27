import React from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAdaptivePolling, type AdaptivePollingResult } from "../hooks/useAdaptivePolling";

function Harness({
  poll,
  activeIntervalMs = 100,
  idleIntervalMs = 1_000,
}: {
  poll: (signal: AbortSignal) => Promise<AdaptivePollingResult>;
  activeIntervalMs?: number;
  idleIntervalMs?: number;
}) {
  const state = useAdaptivePolling({
    poll,
    activeIntervalMs,
    idleIntervalMs,
  });
  return (
    <div>
      <span data-testid="polling">{String(state.isPolling)}</span>
      <button onClick={state.pollNow}>Refresh now</button>
    </div>
  );
}

describe("useAdaptivePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("never overlaps requests and queues a manual refresh behind the in-flight poll", async () => {
    let resolveFirst!: (value: AdaptivePollingResult) => void;
    const first = new Promise<AdaptivePollingResult>((resolve) => {
      resolveFirst = resolve;
    });
    const poll = vi.fn()
      .mockImplementationOnce(() => first)
      .mockResolvedValue(false);

    render(<Harness poll={poll} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(poll).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("polling").textContent).toBe("true");

    await act(async () => {
      screen.getByRole("button", { name: "Refresh now" }).click();
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirst(true);
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it("uses the fast cadence only while work is active", async () => {
    const poll = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValue(false);

    render(<Harness poll={poll} activeIntervalMs={100} idleIntervalMs={1_000} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(99);
    });
    expect(poll).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(poll).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(poll).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(poll).toHaveBeenCalledTimes(3);
  });

  it("stops scheduling when an idle result opts out", async () => {
    const poll = vi.fn().mockResolvedValue({
      active: false,
      continuePolling: false,
    });

    render(<Harness poll={poll} activeIntervalMs={100} idleIntervalMs={1_000} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(poll).toHaveBeenCalledTimes(1);
  });

  it("aborts an in-flight request when the consumer unmounts", async () => {
    let observedSignal: AbortSignal | null = null;
    const poll = vi.fn((signal: AbortSignal) => {
      observedSignal = signal;
      return new Promise<AdaptivePollingResult>(() => {});
    });

    const view = render(<Harness poll={poll} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(observedSignal?.aborted).toBe(false);

    view.unmount();
    expect(observedSignal?.aborted).toBe(true);
  });
});
