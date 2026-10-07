"use client";

import { useState } from "react";

import { ApiError, type ChatMessage, downloadIncidentReport } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useModel } from "@/lib/useModel";

/**
 * "Generar informe de incidente (PDF)" — Práctica 2, roadmap #4.
 *
 * Works from the Chat IA (sends the conversation) and from an alert
 * (sends alert_id; the backend adds the AI analysis + recommendations).
 */
export function IncidentReportButton({
  alertId,
  messages,
  logContext,
  disabled,
}: {
  alertId?: number;
  messages?: ChatMessage[];
  logContext?: string;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const { selected: model } = useModel();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [includeChat, setIncludeChat] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const hasChat = (messages?.length ?? 0) > 0;

  async function generate() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const name = await downloadIncidentReport({
        alert_id: alertId,
        messages: messages ?? [],
        log_context: logContext || undefined,
        title: title.trim() || undefined,
        analyst_notes: notes.trim() || undefined,
        include_transcript: includeChat,
        model: model ?? undefined,
      });
      setMsg(`${t("report_done")} ${name}`);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.status === 429 ? "429 — quota / rate limit" : `${e.status}: ${e.detail.slice(0, 200)}`);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900/40 p-3 space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={generate}
          disabled={busy || disabled}
          className="rounded bg-violet-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white"
        >
          {busy ? t("report_generating") : `⤓ ${t("report_btn")}`}
        </button>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs text-slate-400 hover:text-slate-200"
        >
          {open ? "▼" : "▶"} {t("report_notes_toggle")}
        </button>
      </div>
      {open && (
        <div className="space-y-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder={t("report_title_placeholder")}
            className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
          />
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={4000}
            rows={3}
            placeholder={t("report_notes_placeholder")}
            className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
          />
          {hasChat && (
            <label className="flex items-center gap-2 text-xs opacity-80">
              <input
                type="checkbox"
                checked={includeChat}
                onChange={(e) => setIncludeChat(e.target.checked)}
              />
              {t("report_include_chat")}
            </label>
          )}
        </div>
      )}
      {msg && <div className="text-xs text-emerald-300">{msg}</div>}
      {error && <div className="text-xs text-rose-300">{error}</div>}
    </div>
  );
}
