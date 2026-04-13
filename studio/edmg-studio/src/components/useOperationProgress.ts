import { useCallback, useEffect, useRef, useState } from "react";
import type { ProgressTone } from "./ProgressBar";

export type OperationProgressState = {
  active: boolean;
  value: number;
  label: string;
  detail: string;
  tone: ProgressTone;
};

const IDLE_STATE: OperationProgressState = {
  active: false,
  value: 0,
  label: "",
  detail: "",
  tone: "accent",
};

export function useOperationProgress() {
  const [progress, setProgress] = useState<OperationProgressState>(IDLE_STATE);
  const timerRef = useRef<number | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => stopTimer, [stopTimer]);

  const runOperation = useCallback(
    async <T,>(
      args: {
        label: string;
        detail?: string;
        successDetail?: string;
        successTone?: ProgressTone;
      },
      work: () => Promise<T>,
    ) => {
      stopTimer();
      setProgress({
        active: true,
        value: 12,
        label: args.label,
        detail: args.detail || "Working...",
        tone: "accent",
      });

      timerRef.current = window.setInterval(() => {
        setProgress((current) =>
          current.active
            ? {
                ...current,
                value: Math.min(92, current.value + (current.value < 48 ? 11 : current.value < 72 ? 7 : 3)),
              }
            : current,
        );
      }, 180);

      try {
        const result = await work();
        stopTimer();
        setProgress({
          active: false,
          value: 100,
          label: args.label,
          detail: args.successDetail || "Complete.",
          tone: args.successTone || "success",
        });
        window.setTimeout(() => {
          setProgress((current) => (current.value === 100 ? IDLE_STATE : current));
        }, 1400);
        return result;
      } catch (error) {
        stopTimer();
        const message = error instanceof Error ? error.message : String(error);
        setProgress({
          active: false,
          value: 100,
          label: args.label,
          detail: message,
          tone: "danger",
        });
        throw error;
      }
    },
    [stopTimer],
  );

  return { progress, runOperation, clearProgress: () => setProgress(IDLE_STATE) };
}
