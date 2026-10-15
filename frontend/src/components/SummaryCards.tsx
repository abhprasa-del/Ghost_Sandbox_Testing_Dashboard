import { useState } from "react";
import type { Summary, SummaryBlock } from "../lib/types";

const CARDS: { key: keyof SummaryBlock; label: string; color: string }[] = [
  { key: "total", label: "Total runs", color: "text-slate-900 dark:text-slate-100" },
  { key: "passed", label: "Passed", color: "text-emerald-600 dark:text-emerald-400" },
  { key: "failed", label: "Failed / Timeout", color: "text-red-600 dark:text-red-400" },
  { key: "degraded", label: "Degraded", color: "text-amber-600 dark:text-amber-400" },
  { key: "running", label: "Running", color: "text-sky-600 dark:text-sky-400" },
];

export function SummaryCards({ summary }: { summary: Summary | null }) {
  const [range, setRange] = useState<"today" | "last_7_days">("today");
  const block = summary?.[range];
  return (
    <section aria-label="Summary">
      <div className="mb-2 flex items-center gap-2 text-sm">
        {(["today", "last_7_days"] as const).map((r) => (
          <button
            key={r}
            onClick={() => setRange(r)}
            className={`rounded-full px-3 py-1 ${
              range === r
                ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                : "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
            }`}
          >
            {r === "today" ? "Today" : "Last 7 days"}
          </button>
        ))}
        {block && block.other > 0 && (
          <span className="text-xs text-slate-500">+ {block.other} other (not yet classified)</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {CARDS.map((c) => (
          <div key={c.key} className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
            <div className="text-xs text-slate-500">{c.label}</div>
            <div className={`text-2xl font-semibold ${c.color}`}>{block ? block[c.key] : "…"}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
