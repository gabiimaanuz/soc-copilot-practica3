import type { RiskLevel } from "@/lib/api";

const STYLES: Record<RiskLevel, string> = {
  low: "bg-emerald-900/40 text-emerald-300 border-emerald-700",
  medium: "bg-amber-900/40 text-amber-300 border-amber-700",
  high: "bg-orange-900/40 text-orange-300 border-orange-700",
  critical: "bg-rose-900/50 text-rose-300 border-rose-700",
};

export function RiskBadge({ level }: { level: RiskLevel | null }) {
  if (!level) return null;
  return (
    <span
      className={`rounded border px-2.5 py-0.5 text-xs font-medium uppercase ${STYLES[level]}`}
    >
      {level}
    </span>
  );
}

export function MitreList({ techniques }: { techniques: string[] | null }) {
  if (!techniques || techniques.length === 0) {
    return (
      <span className="text-xs text-slate-500">Sin técnicas mapeadas</span>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {techniques.map((t) => (
        <a
          key={t}
          href={`https://attack.mitre.org/techniques/${t.replace(".", "/")}/`}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded border border-sky-700 bg-sky-950/40 px-2 py-1 text-xs text-cyan-300 hover:bg-sky-900/40"
        >
          {t} ↗
        </a>
      ))}
    </div>
  );
}
