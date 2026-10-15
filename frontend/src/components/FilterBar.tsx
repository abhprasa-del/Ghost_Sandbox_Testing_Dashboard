import { useEffect, useState } from "react";
import type { Filters } from "../lib/types";
import type { FilterKey, UrlState } from "../lib/urlState";

const selectCls =
  "rounded border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

function Select({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <select aria-label={label} className={selectCls} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}: all</option>
      {options.map((o) => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  );
}

export function FilterBar({ state, filters, onChange }: {
  state: UrlState; filters: Filters | null; onChange: (patch: UrlState) => void;
}) {
  const [text, setText] = useState(state.ticket ?? "");

  useEffect(() => setText(state.ticket ?? ""), [state.ticket]);
  useEffect(() => {
    if (text === (state.ticket ?? "")) return;
    const t = setTimeout(() => onChange({ ticket: text, page: "" }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const set = (k: FilterKey) => (v: string) => onChange({ [k]: v, page: "" });
  const active = Object.entries(state).some(([k, v]) => v && !["sort_by", "sort_dir", "page"].includes(k));

  return (
    <div className="space-y-2">
      <input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search GREL number or title…"
        aria-label="Search tickets"
        className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-900"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Select label="Assignee" value={state.assignee ?? ""} options={filters?.assignees ?? []} onChange={set("assignee")} />
        <Select label="SQA" value={state.sqa ?? ""} options={filters?.sqa ?? []} onChange={set("sqa")} />
        <Select label="DevQA" value={state.devqa ?? ""} options={filters?.devqa ?? []} onChange={set("devqa")} />
        <Select label="ALSI" value={state.alsi ?? ""} options={filters?.alsi_versions ?? []} onChange={set("alsi")} />
        <Select label="Mode" value={state.metadata_mode ?? ""} options={filters?.metadata_modes ?? []} onChange={set("metadata_mode")} />
        <Select label="Status" value={state.status ?? ""} options={filters?.statuses ?? []} onChange={set("status")} />
        <label className="flex items-center gap-1 text-sm text-slate-600 dark:text-slate-400">
          From
          <input type="date" className={selectCls} value={state.date_from ?? ""} onChange={(e) => set("date_from")(e.target.value)} />
        </label>
        <label className="flex items-center gap-1 text-sm text-slate-600 dark:text-slate-400">
          To
          <input type="date" className={selectCls} value={state.date_to ?? ""} onChange={(e) => set("date_to")(e.target.value)} />
        </label>
        {active && (
          <button
            className="text-sm text-sky-600 underline dark:text-sky-400"
            onClick={() => onChange({ ticket: "", assignee: "", sqa: "", devqa: "", alsi: "", metadata_mode: "", status: "", date_from: "", date_to: "", page: "" })}
          >
            Clear filters
          </button>
        )}
      </div>
      <p className="text-xs text-slate-500">
        Date range filters on the date of latest run for each ticket + ALSI + mode. Older runs are in the ticket history.
      </p>
    </div>
  );
}
