import { useCallback, useEffect, useState } from "react";

export const FILTER_KEYS = [
  "ticket", "assignee", "sqa", "devqa", "alsi", "metadata_mode", "status",
  "date_from", "date_to", "sort_by", "sort_dir", "page",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type UrlState = Partial<Record<FilterKey, string>>;

export function readUrl(search: string): UrlState {
  const u = new URLSearchParams(search);
  const out: UrlState = {};
  for (const k of FILTER_KEYS) {
    const v = u.get(k);
    if (v) out[k] = v;
  }
  return out;
}

export function writeUrl(state: UrlState): string {
  const u = new URLSearchParams();
  for (const k of FILTER_KEYS) if (state[k]) u.set(k, state[k]!);
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** Filter state kept in the query string so views can be shared. */
export function useUrlState(): [UrlState, (patch: UrlState) => void] {
  const [state, setState] = useState<UrlState>(() => readUrl(window.location.search));

  useEffect(() => {
    const onPop = () => setState(readUrl(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((patch: UrlState) => {
    setState((prev) => {
      const next: UrlState = { ...prev, ...patch };
      for (const k of FILTER_KEYS) if (!next[k]) delete next[k];
      window.history.replaceState(null, "", window.location.pathname + writeUrl(next));
      return next;
    });
  }, []);

  return [state, update];
}
