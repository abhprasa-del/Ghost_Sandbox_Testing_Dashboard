import { useEffect, useState } from "react";

export interface Async<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** Fetch on mount and whenever `deps` change (including the refresh counter). */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [state, setState] = useState<Async<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => !cancelled && setState({ data, error: null, loading: false }),
      (e: Error) => !cancelled && setState((s) => ({ data: s.data, error: e.message, loading: false })),
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
