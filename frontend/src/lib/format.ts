export function formatTime(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(iso));
}

export function formatFull(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, dateStyle: "medium", timeStyle: "short",
  }).format(new Date(iso)) + ` (${tz})`;
}

export function minutesAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const m = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.floor(h / 24)} d ago`;
}

export function csvCell(v: unknown): string {
  const s = v == null ? "" : Array.isArray(v) ? v.join("; ") : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
