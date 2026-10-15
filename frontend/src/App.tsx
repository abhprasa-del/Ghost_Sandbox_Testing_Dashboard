import type { SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Drawer } from "./components/Drawer";
import { FilterBar } from "./components/FilterBar";
import { JOB_COLUMNS, RunsTable } from "./components/RunsTable";
import { SummaryCards } from "./components/SummaryCards";
import { api, type Params } from "./lib/api";
import { csvCell, formatFull, minutesAgo } from "./lib/format";
import type { Run } from "./lib/types";
import { useAsync } from "./lib/useAsync";
import { useUrlState } from "./lib/urlState";

const PAGE_SIZE = 50;

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("theme", next ? "dark" : "light"); } catch { /* ignore */ }
    setDark(next);
  };
  return [dark, toggle] as const;
}

export default function App() {
  const [state, setState] = useUrlState();
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [dark, toggleTheme] = useTheme();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  const meta = useAsync(() => api.meta(), []).data;
  const filters = useAsync(() => api.filters(), [refresh]).data;
  const summary = useAsync(() => api.summary(), [refresh]).data;
  const sync = useAsync(() => api.syncStatus(), [refresh, Math.floor(now / 60000)]).data;

  const params: Params = useMemo(() => ({
    ticket: state.ticket, assignee: state.assignee, sqa: state.sqa, devqa: state.devqa,
    alsi: state.alsi, metadata_mode: state.metadata_mode, status: state.status,
    date_from: state.date_from, date_to: state.date_to,
    sort_by: state.sort_by, sort_dir: state.sort_dir,
  }), [state]);
  const page = Math.max(1, Number(state.page) || 1);

  const runs = useAsync(
    () => api.runs({ ...params, page: String(page), page_size: String(PAGE_SIZE) }),
    [JSON.stringify(params), page, refresh],
  );

  const sorting: SortingState = state.sort_by
    ? [{ id: state.sort_by, desc: state.sort_dir !== "asc" }]
    : [];
  const onSorting = (s: SortingState) =>
    setState({ sort_by: s[0]?.id ?? "", sort_dir: s[0] ? (s[0].desc ? "desc" : "asc") : "", page: "" });

  const tz = meta?.dashboard_tz ?? "Asia/Kolkata";
  const jiraBase = meta?.jira_base_url ?? "";
  const total = runs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const exportCsv = useCallback(async () => {
    const all: Run[] = [];
    for (let p = 1; ; p++) {
      const r = await api.runs({ ...params, page: String(p), page_size: "500" });
      all.push(...r.items);
      if (all.length >= r.total || r.items.length === 0) break;
    }
    const head = ["Ticket", "Title", "ALSI", "Mode", "Assignee", "SQA", "DevQA",
      ...JOB_COLUMNS.map((j) => j.header), "Sandbox #", "Sandbox status", "Not selected", "Last updated"];
    const lines = [head.map(csvCell).join(",")];
    for (const r of all) {
      lines.push([
        r.ticket_key, r.title, r.alsi_version, r.metadata_mode, r.assignee, r.sqa_owner, r.devqa_owner,
        ...JOB_COLUMNS.map((j) => r[j.status] as string | null),
        r.sandbox_build_no, r.sandbox_status, r.not_selected_jobs, r.commented_at,
      ].map(csvCell).join(","));
    }
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "ghost-sandbox-runs.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [params]);

  const last = sync?.last_sync;
  const syncedAt = last?.finished_at ?? last?.started_at;

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Ghost Sandbox Testing Dashboard</h1>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span title={syncedAt ? formatFull(syncedAt, tz) : ""}>
            {sync?.running ? "Syncing…" : `Last synced ${minutesAgo(syncedAt, now)}`}
            {last?.status === "FAILED" && <span className="ml-1 text-red-600" title={last.error_message ?? ""}>(with errors)</span>}
          </span>
          <button onClick={() => setRefresh((n) => n + 1)}
            className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">
            Refresh
          </button>
          <button onClick={toggleTheme} aria-label="Toggle dark mode"
            className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">
            {dark ? "Light" : "Dark"}
          </button>
        </div>
      </header>

      <FilterBar state={state} filters={filters} onChange={setState} />
      <SummaryCards summary={summary} />

      {runs.error && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          Could not load runs: {runs.error}
        </div>
      )}

      <div className="flex items-center justify-between text-sm text-slate-500">
        <span>{runs.loading && !runs.data ? "Loading…" : `${total} row${total === 1 ? "" : "s"}`}</span>
        <button onClick={exportCsv} disabled={total === 0}
          className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-700 dark:hover:bg-slate-800">
          Export CSV
        </button>
      </div>

      <RunsTable
        rows={runs.data?.items ?? []} loading={runs.loading} jiraBase={jiraBase} tz={tz}
        sorting={sorting} onSortingChange={onSorting}
        onSelect={(r) => setSelected(r.run_id)} selectedId={selected}
      />

      <nav className="flex items-center justify-center gap-3 text-sm" aria-label="Pagination">
        <button disabled={page <= 1} onClick={() => setState({ page: String(page - 1) })}
          className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40 dark:border-slate-700">Prev</button>
        <span>Page {page} of {pages}</span>
        <button disabled={page >= pages} onClick={() => setState({ page: String(page + 1) })}
          className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40 dark:border-slate-700">Next</button>
      </nav>

      {selected !== null && (
        <Drawer runId={selected} tz={tz} jiraBase={jiraBase}
          onClose={() => setSelected(null)} onSelectRun={setSelected} />
      )}
    </div>
  );
}
