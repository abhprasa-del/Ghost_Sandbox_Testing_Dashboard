import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { formatFull } from "../lib/format";
import { CATEGORY_TONE, jobLabel, jobTone } from "../lib/status";
import type { JobResult, RunDetail } from "../lib/types";
import { useAsync } from "../lib/useAsync";
import { Badge } from "./Badge";

function Link({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-sky-700 hover:underline dark:text-sky-400">
      {children}
    </a>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

function JobCard({ job, notSelected }: { job: JobResult; notSelected: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={job.job_url}><span className="font-medium">{job.job_name}</span></Link>
        {!job.job_url && <span className="font-medium">{job.job_name}</span>}
        <Badge tone={jobTone(job.job_status, job.outcome)}>{jobLabel(job.job_status, job.outcome, notSelected)}</Badge>
        {job.outcome && job.outcome !== "NA" && <span className="text-xs text-slate-500">{job.outcome}</span>}
      </div>
      {job.result_text && job.build_artifacts.length === 0 && job.baseline_suites.length === 0 && !job.bats_groups?.length && <p className="mt-1 break-words text-xs text-slate-600 dark:text-slate-400">{job.result_text}</p>}
      <div className="mt-1 flex flex-wrap gap-3 text-xs">
        <Link href={job.summary_url}>Summary</Link>
        <Link href={job.analysis_url}>Analysis</Link>
        <Link href={job.plots_url}>Plots</Link>
      </div>
      {!!job.bats_groups?.length && (
        <ul className="mt-1 space-y-0.5 text-xs">
          {job.bats_groups.map((g) => (
            <li key={g.name} className="flex flex-wrap items-center gap-x-1">
              {g.name_url ? <Link href={g.name_url}>{g.name}</Link> : <span className="font-medium">{g.name}</span>}
              <span>:</span>
              {g.links.map((l, i) => (
                <span key={l.url} className="flex items-center gap-1">
                  {i > 0 && <span className="text-slate-400">|</span>}
                  <Link href={l.url}>{l.label}</Link>
                </span>
              ))}
              {g.note && <span className="text-slate-600 dark:text-slate-400">{g.note}</span>}
            </li>
          ))}
        </ul>
      )}
      {job.build_artifacts.map((a) => (
        <div key={a.download_url} className="mt-2 text-xs">
          <div className="mb-1 flex items-center gap-2">
            <span className="font-medium">{a.artifact_type}</span>
            {a.wget_command && <CopyButton text={a.wget_command} />}
          </div>
          <code className="block break-all rounded bg-slate-100 p-1.5 dark:bg-slate-800">{a.wget_command ?? a.download_url}</code>
        </div>
      ))}
      {job.baseline_suites.length > 0 && (
        <table className="mt-2 w-full text-xs">
          <tbody>
            {job.baseline_suites.map((s) => (
              <tr key={s.suite_name}>
                <td className="py-0.5 pr-3 font-medium">{s.suite_name}</td>
                <td className="space-x-3">
                  <Link href={s.job_link}>Job</Link>
                  <Link href={s.report_link}>Report</Link>
                  <Link href={s.siam_link}>SIAM</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Details({ d, tz }: { d: RunDetail; tz: string }) {
  const notSel = d.not_selected_jobs ?? [];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <span className="text-slate-500">ALSI</span><span>{d.alsi_version ?? "—"}</span>
        <span className="text-slate-500">Mode</span><span>{d.metadata_mode}</span>
        <span className="text-slate-500">Assignee</span><span>{d.assignee ?? "—"}</span>
        <span className="text-slate-500">SQA</span><span>{d.sqa_owner ?? "—"}</span>
        <span className="text-slate-500">DevQA</span><span>{d.devqa_owner ?? "—"}</span>
        <span className="text-slate-500">Ticket status</span><span>{d.ticket_status ?? "—"}</span>
        <span className="text-slate-500">Sandbox</span>
        <span>
          <Link href={d.sandbox_build_url}>{d.sandbox_build_no ? `#${d.sandbox_build_no}` : "—"}</Link> {d.sandbox_status}
        </span>
        <span className="text-slate-500">Ghost version</span><span className="break-all">{d.ghost_version ?? "—"}</span>
        <span className="text-slate-500">Commented</span>
        <span>{formatFull(d.commented_at, tz)}{d.comment_edited ? " (edited)" : ""}</span>
      </div>
      <div className="space-y-2">
        {d.job_results.map((j) => <JobCard key={j.job_name} job={j} notSelected={notSel.includes(j.job_name)} />)}
      </div>
      {notSel.length > 0 && (
        <div>
          <div className="mb-1 text-sm text-slate-500">Not selected</div>
          <div className="flex flex-wrap gap-1">{notSel.map((n) => <Badge key={n} tone="grey">{n}</Badge>)}</div>
        </div>
      )}
      {d.ghost_crashes_url && (
        <div className="text-sm"><Link href={d.ghost_crashes_url}>Ghost crashes (if any)</Link></div>
      )}
    </div>
  );
}

function History({ ticket, currentId, tz, onSelect }: {
  ticket: string; currentId: number; tz: string; onSelect: (id: number) => void;
}) {
  const t = useAsync(() => api.ticket(ticket), [ticket]);
  if (t.loading && !t.data) return <p className="text-sm text-slate-500">Loading history…</p>;
  if (t.error) return <p className="text-sm text-red-600">{t.error}</p>;
  return (
    <ul className="space-y-2">
      {t.data!.runs.map((r) => (
        <li key={r.run_id}>
          <button
            onClick={() => onSelect(r.run_id)}
            className={`w-full rounded-lg border p-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${
              r.run_id === currentId ? "border-sky-500" : "border-slate-200 dark:border-slate-800"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{r.alsi_version}</span>
              <Badge tone={r.metadata_mode === "DEFAULT" ? "grey" : "amber"}>{r.metadata_mode}</Badge>
              <Badge tone={CATEGORY_TONE[r.category] ?? "grey"}>{r.category}</Badge>
              <span className="text-xs text-slate-500">{r.sandbox_build_no ? `#${r.sandbox_build_no}` : ""}</span>
              <span className="ml-auto text-xs text-slate-500">{formatFull(r.commented_at, tz)}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {r.jobs.map((j) => (
                <Badge key={j.job_name} tone={jobTone(j.job_status, j.outcome)} title={j.job_status}>
                  {j.job_name.replace(" build", "").replace(" Regression", "")}
                </Badge>
              ))}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function Drawer({ runId, tz, jiraBase, onClose, onSelectRun }: {
  runId: number; tz: string; jiraBase: string; onClose: () => void; onSelectRun: (id: number) => void;
}) {
  const [tab, setTab] = useState<"details" | "history">("details");
  const run = useAsync(() => api.run(runId), [runId]);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Move focus into the dialog on open and give it back to the opener on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => opener?.focus?.();
  }, []);

  const trapFocus = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !dialogRef.current) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) {
      e.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === dialogRef.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const d = run.data;
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 sm:p-4" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Run details"
        tabIndex={-1}
        onKeyDown={trapFocus}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col overflow-hidden bg-white shadow-xl outline-none dark:bg-slate-900 sm:h-auto sm:max-h-[85vh] sm:w-[90vw] sm:max-w-[960px] sm:rounded-lg"
      >
        <div className="shrink-0 px-4 pt-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              {d ? (
                <>
                  <a href={`${jiraBase}/browse/${d.ticket_key}`} target="_blank" rel="noreferrer"
                     className="text-lg font-semibold text-sky-700 hover:underline dark:text-sky-400">{d.ticket_key}</a>
                  <p className="text-sm text-slate-600 dark:text-slate-400">{d.title}</p>
                </>
              ) : <p className="text-slate-500">{run.error ?? "Loading…"}</p>}
            </div>
            <button onClick={onClose} aria-label="Close" className="rounded px-2 py-1 text-xl hover:bg-slate-100 dark:hover:bg-slate-800">×</button>
          </div>
          {d && (
            <div className="flex gap-2 border-b border-slate-200 dark:border-slate-800">
              {(["details", "history"] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)}
                  className={`px-3 py-1.5 text-sm capitalize ${tab === t ? "border-b-2 border-sky-500 font-medium" : "text-slate-500"}`}>
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>
        {d && (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {tab === "details"
              ? <Details d={d} tz={tz} />
              : <History ticket={d.ticket_key} currentId={d.run_id} tz={tz}
                  onSelect={(id) => { onSelectRun(id); setTab("details"); }} />}
          </div>
        )}
      </div>
    </div>
  );
}
