"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { IncidentReportButton } from "@/components/IncidentReportButton";
import { ModelSelector } from "@/components/ModelSelector";
import { MitreList, RiskBadge } from "@/components/RiskBadge";
import { type AlertDetail, getAlert, recommendActions, type RecommendResponse } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { useModel } from "@/lib/useModel";

function RespondInner() {
  const params = useSearchParams();
  const alertIdParam = params.get("alert_id");
  const alertId = alertIdParam ? Number(alertIdParam) : null;

  const [alert, setAlert] = useState<AlertDetail | null>(null);
  const [rec, setRec] = useState<RecommendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [recommending, setRecommending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { selected: model } = useModel();
  const auth = useRequireAuth();
  const { t } = useI18n();

  useEffect(() => {
    if (!alertId) return;
    setLoading(true);
    setError(null);
    getAlert(alertId)
      .then((a) => {
        setAlert(a);
        if (a.recommendations.length > 0) {
          const latest = a.recommendations[a.recommendations.length - 1];
          setRec({ id: latest.id, alert_id: a.id, actions: latest.actions, priority: latest.priority, learning_notes: latest.learning_notes ?? "" });
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [alertId]);

  async function onRecommend() {
    if (!alertId) return;
    setRecommending(true);
    setError(null);
    setRec(null);
    try {
      setRec(await recommendActions({ alert_id: alertId, model: model ?? undefined }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRecommending(false);
    }
  }

  if (!auth.ready) return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;

  if (!alertId) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">{t("respond_title")}</h1>
        <p className="text-slate-400">
          {t("respond_no_alert")}{" "}
          <Link href="/alerts" className="text-cyan-400 hover:underline">Alertas</Link>.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("respond_title")}</h1>
          <p className="text-slate-400 mt-1">{t("respond_subtitle")}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <ModelSelector compact />
          <Link href="/alerts" className="text-sm text-cyan-400 hover:underline">
            {t("respond_new_alert")}
          </Link>
        </div>
      </div>

      {loading && <p className="text-slate-400">{t("respond_loading_alert")} #{alertId}…</p>}

      {error && (
        <div className="rounded border border-rose-700 bg-rose-950/40 p-4 text-sm text-rose-300">
          <strong>{t("alerts_error")}</strong> {error}
        </div>
      )}

      {alert && (
        <div className="rounded-lg border border-ink-700 bg-ink-900/60 p-6 space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">
                Alerta #{alert.id}
                {alert.source && <span className="ml-2 text-xs text-slate-500">{alert.source}</span>}
              </h2>
              <p className="mt-1 text-slate-200">{alert.summary}</p>
            </div>
            <RiskBadge level={alert.risk_level} />
          </div>
          <pre className="whitespace-pre-wrap rounded bg-slate-950 p-3 font-mono text-xs text-slate-300">{alert.log}</pre>
          <MitreList techniques={alert.mitre_techniques} />
        </div>
      )}

      {alert && (
        <button onClick={onRecommend} disabled={recommending}
          className="rounded bg-emerald-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white">
          {recommending ? t("respond_recommending_btn") : rec ? t("respond_another_btn") : t("respond_recommend_btn")}
        </button>
      )}

      {rec && (
        <div className="rounded-lg border border-ink-700 bg-ink-900/60 p-6 space-y-4">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">
              {t("respond_recommendation")}{" "}
              {rec.id != null && <span className="text-xs text-slate-500">#{rec.id}</span>}
            </h2>
            <RiskBadge level={rec.priority} />
          </div>
          <ol className="space-y-3">
            {rec.actions.map((a, i) => (
              <li key={i} className="rounded border border-ink-700 bg-slate-950/40 p-4">
                <div className="font-semibold text-slate-100">{i + 1}. {a.title}</div>
                <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-slate-300">{a.detail}</pre>
                <p className="mt-2 text-xs text-slate-400 italic">💡 {a.rationale}</p>
              </li>
            ))}
          </ol>
          {rec.learning_notes && (
            <div className="rounded border border-sky-800 bg-sky-950/30 p-4 text-sm">
              <h3 className="font-semibold text-cyan-300 mb-1">{t("respond_learning")}</h3>
              <p className="text-slate-300 whitespace-pre-line">{rec.learning_notes}</p>
            </div>
          )}
        </div>
      )}

      {alert && <IncidentReportButton alertId={alert.id} disabled={recommending} />}
    </div>
  );
}

export default function RespondPage() {
  return (
    <Suspense fallback={<div className="p-6 max-w-5xl mx-auto"><p className="text-slate-400">Cargando…</p></div>}>
      <RespondInner />
    </Suspense>
  );
}
