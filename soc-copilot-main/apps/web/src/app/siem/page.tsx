"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { MitreList, RiskBadge } from "@/components/RiskBadge";
import {
  type AlertDetail,
  type AlertSummary,
  ApiError,
  analyzeStoredAlert,
  getWazuhStatus,
  listAlerts,
  type WazuhStatus,
  wazuhPullNow,
} from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { useModel } from "@/lib/useModel";

type Filter = "pending" | "analyzed" | "all";
const REFRESH_MS = 15_000;

function levelClass(level: number | null): string {
  if (level == null) return "bg-slate-800 text-slate-300 border-slate-600";
  if (level >= 13) return "bg-rose-900/50 text-rose-300 border-rose-700";
  if (level >= 10) return "bg-orange-900/40 text-orange-300 border-orange-700";
  if (level >= 7) return "bg-amber-900/40 text-amber-300 border-amber-700";
  return "bg-emerald-900/40 text-emerald-300 border-emerald-700";
}

function fmt(ts: string | null, never: string): string {
  return ts ? new Date(ts).toLocaleString() : never;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const parsed = JSON.parse(e.detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch {
      /* plain text detail */
    }
    return e.detail;
  }
  return e instanceof Error ? e.message : String(e);
}

function IntegrationPanel() {
  const { t } = useI18n();
  const [status, setStatus] = useState<WazuhStatus | null>(null);
  const [pulling, setPulling] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    getWazuhStatus()
      .then(setStatus)
      .catch((e) => setMsg(errMsg(e)));
  }, []);

  useEffect(load, [load]);

  async function pull() {
    setPulling(true);
    setMsg(null);
    try {
      const r = await wazuhPullNow();
      setMsg(`${t("siem_pull_result")}: ${r.created} · dup ${r.duplicates} · fetched ${r.fetched}`);
      load();
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setPulling(false);
    }
  }

  const pill = (on: boolean) => (
    <span
      className={
        "ml-2 rounded border px-1.5 py-0.5 text-[10px] uppercase " +
        (on
          ? "border-emerald-700 bg-emerald-900/40 text-emerald-300"
          : "border-slate-600 bg-slate-800 text-slate-400")
      }
    >
      {on ? t("siem_enabled") : t("siem_disabled")}
    </span>
  );

  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900/60 p-4 text-sm space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{t("siem_integration")}</h2>
        <button
          type="button"
          onClick={pull}
          disabled={pulling || !status?.pull_enabled}
          title={
            status && !status.pull_enabled
              ? "Pull desactivado: configura WAZUH_INDEXER_URL en el .env"
              : undefined
          }
          className="rounded bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium text-white"
        >
          {pulling ? t("siem_pulling") : t("siem_pull_now")}
        </button>
      </div>
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div>
            <div className="opacity-60">{t("siem_push")}{pill(status.push_enabled)}</div>
            <div className="mt-1">
              {t("siem_last_push")}: {fmt(status.push_last_received, t("siem_never"))}
            </div>
          </div>
          <div>
            <div className="opacity-60">{t("siem_pull")}{pill(status.pull_enabled)}</div>
            <div className="mt-1">
              {t("siem_last_pull")}: {fmt(status.pull_last_run, t("siem_never"))}
            </div>
            {status.pull_last_error && (
              <div className="mt-1 text-rose-300">{status.pull_last_error}</div>
            )}
          </div>
          <div>
            <div className="opacity-60">{t("siem_last24h")}</div>
            <div className="mt-1 text-lg font-semibold">{status.alerts_last_24h}</div>
          </div>
          <div>
            <div className="opacity-60">
              {t("siem_pending_count")} · {t("siem_min_level")} {status.min_rule_level}
            </div>
            <div className="mt-1 text-lg font-semibold">{status.alerts_pending}</div>
          </div>
        </div>
      )}
      {msg && <div className="text-xs text-slate-300">{msg}</div>}
    </div>
  );
}

export default function SiemPage() {
  const auth = useRequireAuth();
  const { t } = useI18n();
  const { selected: model } = useModel();
  const [filter, setFilter] = useState<Filter>("pending");
  const [alerts, setAlerts] = useState<AlertSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [opened, setOpened] = useState<AlertDetail | null>(null);

  const load = useCallback(() => {
    const pending = filter === "all" ? undefined : filter === "pending";
    listAlerts(100, 0, { origin: "wazuh", pending })
      .then((rows) => {
        setAlerts(rows);
        setError(null);
      })
      .catch((e) => setError(errMsg(e)));
  }, [filter]);

  useEffect(() => {
    if (!auth.user) return;
    load();
    if (!autoRefresh) return;
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [auth.user, load, autoRefresh]);

  async function analyze(id: number) {
    setBusyId(id);
    setError(null);
    try {
      const detail = await analyzeStoredAlert(id, model ?? undefined);
      setOpened(detail);
      load();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusyId(null);
    }
  }

  if (!auth.ready) {
    return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;
  }

  const filters: { key: Filter; label: string }[] = [
    { key: "pending", label: t("siem_filter_pending") },
    { key: "analyzed", label: t("siem_filter_analyzed") },
    { key: "all", label: t("siem_filter_all") },
  ];

  return (
    <div className="p-6 max-w-[1280px] mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{t("siem_title")}</h1>
        <p className="text-slate-400 mt-1">{t("siem_subtitle")}</p>
      </div>

      {auth.user?.role === "admin" && <IntegrationPanel />}

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-md border border-ink-700 overflow-hidden text-xs">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={
                "px-3 py-1.5 " +
                (filter === f.key ? "bg-cyan-500 text-ink-950" : "opacity-60 hover:opacity-90")
              }
            >
              {f.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs opacity-80">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          {t("siem_auto_refresh")}
        </label>
        <button
          type="button"
          onClick={load}
          className="ml-auto rounded border border-ink-700 px-3 py-1.5 text-xs hover:bg-ink-800"
        >
          {t("siem_refresh")}
        </button>
      </div>

      {error && (
        <div className="rounded border border-rose-700 bg-rose-950/40 p-4 text-sm text-rose-300">
          <strong>{t("alerts_error")}</strong> {error}
        </div>
      )}

      {opened && (
        <div className="space-y-4 rounded-lg border border-ink-700 bg-ink-900/60 p-6">
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold">
              {t("alerts_summary")} <span className="text-xs text-slate-500">#{opened.id}</span>
            </h2>
            <div className="flex items-center gap-2">
              <RiskBadge level={opened.risk_level} />
              <button
                type="button"
                onClick={() => setOpened(null)}
                className="text-xs opacity-60 hover:opacity-100"
                aria-label="close"
              >
                ✕
              </button>
            </div>
          </div>
          <p className="text-slate-200 leading-relaxed">{opened.summary}</p>
          <MitreList techniques={opened.mitre_techniques} />
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">
            {opened.reasoning}
          </p>
          <Link
            href={`/respond?alert_id=${opened.id}`}
            className="inline-block rounded bg-emerald-600 hover:brightness-110 px-4 py-2 text-sm font-medium text-white"
          >
            {t("alerts_next_step")}
          </Link>
        </div>
      )}

      {!alerts && !error && <p className="text-slate-400">{t("history_loading")}</p>}
      {alerts && alerts.length === 0 && <p className="text-slate-400">{t("siem_empty")}</p>}

      {alerts && alerts.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("siem_col_level")}</th>
                <th className="px-3 py-2">{t("siem_col_rule")}</th>
                <th className="px-3 py-2">{t("siem_col_agent")}</th>
                <th className="px-3 py-2">{t("siem_col_event")}</th>
                <th className="px-3 py-2">{t("history_col_risk")}</th>
                <th className="px-3 py-2">{t("history_col_mitre")}</th>
                <th className="px-3 py-2">{t("siem_col_status")}</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className="border-t border-ink-700 align-top">
                  <td className="px-3 py-2">
                    <span className={`rounded border px-2 py-0.5 text-xs font-mono ${levelClass(a.rule_level)}`}>
                      {a.rule_level ?? "—"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-200 max-w-md">{a.summary ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-400">{a.agent_name ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                    {new Date(a.event_at ?? a.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2"><RiskBadge level={a.risk_level} /></td>
                  <td className="px-3 py-2 text-xs text-slate-400">
                    {(a.mitre_techniques ?? []).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {a.analyzed_at ? (
                      <span className="text-emerald-300">{t("siem_status_analyzed")}</span>
                    ) : (
                      <span className="text-amber-300">{t("siem_status_pending")}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {a.analyzed_at ? (
                      <Link href={`/respond?alert_id=${a.id}`} className="text-xs text-cyan-400 hover:underline">
                        {t("siem_view")}
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={() => analyze(a.id)}
                        disabled={busyId === a.id}
                        className="rounded bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1 text-xs font-medium text-white"
                      >
                        {busyId === a.id ? t("siem_analyzing_btn") : t("siem_analyze_btn")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
