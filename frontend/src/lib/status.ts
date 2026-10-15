export type Tone = "green" | "red" | "amber" | "grey";

/**
 * Badge colour for one job. Mirrors the backend category logic:
 * red FAILURE/TIMEOUT; amber RUNNING/STARTING/UNSTABLE or a DEGRADED outcome;
 * grey SKIPPED or not selected; green otherwise (Completed / passed).
 */
export function jobTone(status: string | null | undefined, outcome?: string | null): Tone {
  if (!status) return "grey";
  const s = status.toUpperCase();
  if (s === "FAILURE" || s === "TIMEOUT") return "red";
  if (s === "RUNNING" || s === "STARTING" || s === "UNSTABLE") return "amber";
  if ((outcome ?? "").toUpperCase() === "DEGRADED") return "amber";
  if (s === "SKIPPED") return "grey";
  if (s === "COMPLETED") return "green";
  return "grey";
}

export function jobLabel(
  status: string | null | undefined,
  outcome?: string | null,
  notSelected = false,
): string {
  if (!status) return notSelected ? "Not selected" : "—";
  if ((outcome ?? "").toUpperCase() === "DEGRADED") return "Degraded";
  return status;
}

export const TONE_CLASSES: Record<Tone, string> = {
  green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  red: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  grey: "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

export const CATEGORY_TONE: Record<string, Tone> = {
  passed: "green",
  failed: "red",
  degraded: "amber",
  running: "amber",
  other: "grey",
};
