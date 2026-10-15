import { TONE_CLASSES, type Tone } from "../lib/status";

export function Badge({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
