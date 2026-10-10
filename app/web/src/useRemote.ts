import { useCallback, useEffect, useState } from "react";

export type Remote<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: unknown };

/** Runs `load` whenever its identity changes and exposes `retry`. Memoise `load` with useCallback. */
export function useRemote<T>(load: () => Promise<T>): { state: Remote<T>; retry: () => void } {
  const [state, setState] = useState<Remote<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
    load().then(
      (data) => {
        if (current) setState({ status: "success", data });
      },
      (error: unknown) => {
        if (current) setState({ status: "error", error });
      },
    );
    return () => {
      current = false;
    };
  }, [load, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
