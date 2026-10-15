import {
  createColumnHelper, flexRender, getCoreRowModel, useReactTable, type SortingState,
} from "@tanstack/react-table";
import { useMemo } from "react";
import { jobLabel, jobTone, CATEGORY_TONE, type Tone } from "../lib/status";
import { formatTime } from "../lib/format";
import type { Run } from "../lib/types";
import { Badge } from "./Badge";

interface JobCol {
  header: string;
  job: string; // canonical job name, as returned by /api/meta
  status: keyof Run;
  outcome?: keyof Run;
}

export const JOB_COLUMNS: JobCol[] = [
  { header: "PERF", job: "PERF", status: "have_perf", outcome: "perf_outcome" },
  { header: "LOAD", job: "LOAD", status: "have_load", outcome: "load_outcome" },
  { header: "BATS", job: "BATS", status: "have_bats" },
  { header: "ASAN", job: "ASAN build", status: "asan_status" },
  { header: "LSAN", job: "LSAN build", status: "lsan_status" },
  { header: "TSAN", job: "TSAN build", status: "tsan_status" },
  { header: "Baseline", job: "Baseline Regression", status: "have_baseline", outcome: "baseline_outcome" },
];

const col = createColumnHelper<Run>();
const DOT: Record<Tone, string> = {
  green: "bg-emerald-500", red: "bg-red-500", amber: "bg-amber-500", grey: "bg-slate-400",
};

export function RunsTable({ rows, loading, jiraBase, tz, sorting, onSortingChange, onSelect, selectedId }: {
  rows: Run[]; loading: boolean; jiraBase: string; tz: string;
  sorting: SortingState; onSortingChange: (s: SortingState) => void;
  onSelect: (run: Run) => void; selectedId: number | null;
}) {
  const columns = useMemo(() => [
    col.accessor("ticket_key", {
      header: "GREL ID",
      cell: (c) => (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span
            title={c.row.original.category}
            className={`inline-block h-2 w-2 rounded-full ${DOT[CATEGORY_TONE[c.row.original.category] ?? "grey"]}`}
          />
          <a
            href={`${jiraBase}/browse/${c.getValue()}`} target="_blank" rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            {c.getValue()}
          </a>
        </span>
      ),
    }),
    col.accessor("title", {
      header: "Title",
      cell: (c) => <span className="line-clamp-2 min-w-[14rem] max-w-md" title={c.getValue()}>{c.getValue()}</span>,
    }),
    col.accessor("alsi_version", { header: "ALSI", cell: (c) => c.getValue() ?? "—" }),
    col.accessor("metadata_mode", {
      header: "Mode",
      cell: (c) => (
        <Badge tone={c.getValue() === "DEFAULT" ? "grey" : "amber"}>{c.getValue()}</Badge>
      ),
    }),
    col.accessor("assignee", { header: "Assignee", cell: (c) => c.getValue() ?? "—" }),
    col.accessor("sqa_owner", { header: "SQA", cell: (c) => c.getValue() ?? "—" }),
    col.accessor("devqa_owner", { header: "DevQA", cell: (c) => c.getValue() ?? "—" }),
    ...JOB_COLUMNS.map((j) =>
      col.accessor((r) => r[j.status] as string | null, {
        id: j.status,
        header: j.header,
        cell: (c) => {
          const r = c.row.original;
          const status = c.getValue();
          const notSelected = !status && (r.not_selected_jobs ?? []).includes(j.job);
          const outcome = j.outcome ? (r[j.outcome] as string | null) : null;
          return (
            <Badge tone={jobTone(status, outcome)} title={j.job}>
              {jobLabel(status, outcome, notSelected)}
            </Badge>
          );
        },
      }),
    ),
    col.accessor("sandbox_build_no", {
      header: "Sandbox #",
      cell: (c) => {
        if (!c.getValue()) return "—";
        const url = c.row.original.sandbox_build_url;
        return url ? (
          <a
            href={url} target="_blank" rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-sky-700 hover:underline dark:text-sky-400"
          >
            #{c.getValue()}
          </a>
        ) : (
          `#${c.getValue()}`
        );
      },
    }),
    col.accessor("commented_at", { header: "Last updated", cell: (c) => <span className="whitespace-nowrap">{formatTime(c.getValue(), tz)}</span> }),
  ], [jiraBase, tz]);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    manualSorting: true,
    enableSortingRemoval: true,
    onSortingChange: (u) => onSortingChange(typeof u === "function" ? u(sorting) : u),
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => String(r.run_id),
  });

  return (
    <div className="max-h-[70vh] overflow-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-slate-100 dark:bg-slate-800">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const dir = h.column.getIsSorted();
                return (
                  <th
                    key={h.id}
                    onClick={h.column.getToggleSortingHandler()}
                    aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}
                    className="cursor-pointer select-none whitespace-nowrap px-2 py-2 text-left font-semibold text-slate-600 dark:text-slate-300"
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    <span className="ml-1 text-xs">{dir === "asc" ? "▲" : dir === "desc" ? "▼" : ""}</span>
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className={loading ? "opacity-50" : ""}>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onSelect(row.original)}
              className={`cursor-pointer border-t border-slate-100 hover:bg-sky-50 dark:border-slate-800 dark:hover:bg-slate-800 ${
                selectedId === row.original.run_id ? "bg-sky-50 dark:bg-slate-800" : ""
              }`}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-2 py-1.5 align-top">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && rows.length === 0 && (
        <div className="p-10 text-center text-slate-500">No runs match these filters.</div>
      )}
      {loading && rows.length === 0 && <div className="p-10 text-center text-slate-500">Loading…</div>}
    </div>
  );
}
