import type { Filters, Meta, RunDetail, RunsPage, Summary, SyncStatus, TicketDetail } from "./types";

export type Params = Record<string, string | undefined>;

function qs(params: Params): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function get<T>(path: string, params: Params = {}): Promise<T> {
  const r = await fetch(`/api${path}${qs(params)}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  runs: (p: Params) => get<RunsPage>("/runs", p),
  run: (id: number) => get<RunDetail>(`/runs/${id}`),
  ticket: (key: string) => get<TicketDetail>(`/tickets/${encodeURIComponent(key)}`),
  summary: () => get<Summary>("/summary"),
  filters: () => get<Filters>("/filters"),
  meta: () => get<Meta>("/meta"),
  syncStatus: () => get<SyncStatus>("/sync/status"),
};
