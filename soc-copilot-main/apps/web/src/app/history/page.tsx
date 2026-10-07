"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { RiskBadge } from "@/components/RiskBadge";
import { type AlertSummary, listAlerts } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export default function HistoryPage() {
  const [alerts, setAlerts] = useState<AlertSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const auth = useRequireAuth();
  const { t } = useI18n();

  useEffect(() => {
    if (!auth.user) return;
    listAlerts(100)
      .then(setAlerts)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [auth.user]);

  if (!auth.ready) {
    return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-bold tracking-tight">{t("history_title")}</h1>
        <Link href="/alerts" className="text-sm text-cyan-400 hover:underline">
          {t("history_new_alert")}
        </Link>
      </div>

      {error && (
        <div className="rounded border border-rose-700 bg-rose-950/40 p-4 text-sm text-rose-300">
          <strong>{t("alerts_error")}</strong> {error}
        </div>
      )}

      {!alerts && !error && <p className="text-slate-400">{t("history_loading")}</p>}

      {alerts && alerts.length === 0 && (
        <p className="text-slate-400">
          {t("history_empty")}{" "}
          <Link href="/alerts" className="text-cyan-400 hover:underline">Alertas</Link>.
        </p>
      )}

      {alerts && alerts.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">{t("history_col_id")}</th>
              <th className="px-3 py-2">{t("history_col_date")}</th>
              <th className="px-3 py-2">{t("history_col_source")}</th>
              <th className="px-3 py-2">{t("history_col_summary")}</th>
              <th className="px-3 py-2">{t("history_col_risk")}</th>
              <th className="px-3 py-2">{t("history_col_mitre")}</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id} className="border-t border-ink-700">
                <td className="px-3 py-2 text-slate-500">{a.id}</td>
                <td className="px-3 py-2 text-slate-400">{new Date(a.created_at).toLocaleString()}</td>
                <td className="px-3 py-2 text-slate-400">{a.source ?? "—"}</td>
                <td className="px-3 py-2 text-slate-200 max-w-md truncate">{a.summary ?? "—"}</td>
                <td className="px-3 py-2"><RiskBadge level={a.risk_level} /></td>
                <td className="px-3 py-2 text-xs text-slate-400">{(a.mitre_techniques ?? []).join(", ") || "—"}</td>
                <td className="px-3 py-2">
                  <Link href={`/respond?alert_id=${a.id}`} className="text-xs text-cyan-400 hover:underline">
                    {t("history_open")}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
