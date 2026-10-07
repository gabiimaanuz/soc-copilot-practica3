"use client";

import { useModel } from "@/lib/useModel";

export function ModelSelector({ compact = false }: { compact?: boolean }) {
  const { info, selected, choose, error } = useModel();

  if (error) {
    return (
      <span className="text-xs text-rose-400" title={error}>
        modelo: error
      </span>
    );
  }
  if (!info || !selected) {
    return <span className="text-xs text-slate-500">modelo: …</span>;
  }

  return (
    <label
      className={`flex items-center gap-2 ${compact ? "text-xs" : "text-sm"} text-slate-400`}
    >
      <span>modelo:</span>
      <select
        value={selected}
        onChange={(e) => choose(e.target.value)}
        className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
      >
        {info.available.map((m) => (
          <option key={m} value={m}>
            {m}
            {m === info.default ? " (default)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
