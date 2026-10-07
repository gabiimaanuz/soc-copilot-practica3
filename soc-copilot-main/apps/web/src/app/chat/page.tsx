"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { IncidentReportButton } from "@/components/IncidentReportButton";
import { ModelSelector } from "@/components/ModelSelector";
import { type ChatMessage, type KBStatus, kbStatus, sendChat } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { useModel } from "@/lib/useModel";

function SourcePill({ id }: { id: string }) {
  const [kind, ref] = id.split(":");
  const url =
    kind === "mitre"
      ? `https://attack.mitre.org/techniques/${ref.replace(".", "/")}/`
      : kind === "owasp"
        ? `https://owasp.org/Top10/${ref.replace(":", "_").replace("2025", "2025/")}`
        : "#";
  const color =
    kind === "mitre"
      ? "border-sky-700 bg-sky-950/40 text-cyan-300"
      : "border-emerald-700 bg-emerald-950/40 text-emerald-300";
  return (
    <a href={url} target="_blank" rel="noopener noreferrer"
      className={`rounded border px-2 py-0.5 text-[11px] ${color}`}>
      {ref} ↗
    </a>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [logContext, setLogContext] = useState("");
  const [showLogContext, setShowLogContext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSources, setLastSources] = useState<string[]>([]);
  const [kb, setKb] = useState<KBStatus | null>(null);
  const { selected: model } = useModel();
  const scrollRef = useRef<HTMLDivElement>(null);
  const auth = useRequireAuth();
  const { t } = useI18n();

  const STARTERS = [t("chat_starter_1"), t("chat_starter_2"), t("chat_starter_3")];

  useEffect(() => {
    kbStatus().then(setKb).catch(() => setKb(null));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  async function send(content: string) {
    const trimmed = content.trim();
    if (!trimmed || loading) return;
    const userMsg: ChatMessage = { role: "user", content: trimmed };
    const next: ChatMessage[] = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const res = await sendChat({ messages: next, log_context: logContext || undefined, model: model ?? undefined });
      setMessages([...next, { role: "assistant", content: res.reply }]);
      setLastSources(res.sources);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (!auth.ready) {
    return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;
  }

  return (
    <div className="p-6 max-w-4xl mx-auto flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("chat_title")}</h1>
          <p className="text-slate-400 mt-1 text-sm">{t("chat_subtitle")}</p>
          <p className="text-slate-500 mt-0.5 text-xs">{t("chat_lang_hint")}</p>
        </div>
        <div className="flex flex-col items-end gap-1 text-xs">
          {kb ? (
            <span className="text-slate-400">
              KB: {kb.total} {t("chat_kb_docs")} ({kb.mitre} MITRE · {kb.owasp} OWASP)
            </span>
          ) : (
            <span className="text-amber-400">{t("chat_kb_unavailable")}</span>
          )}
          <ModelSelector compact />
          <Link href="/alerts" className="px-3 py-2 rounded-md text-xs border border-ink-700 bg-ink-850 hover:bg-ink-800 text-slate-300">
            {t("chat_back_alerts")}
          </Link>
        </div>
      </div>

      {messages.length === 0 && (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">{t("chat_starters_label")}</p>
          <div className="flex flex-col gap-2">
            {STARTERS.map((s) => (
              <button key={s} type="button" onClick={() => send(s)}
                className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-left text-sm hover:border-slate-500">
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 min-h-[300px] overflow-y-auto space-y-3 rounded-lg border border-ink-700 bg-slate-950/40 p-4">
        {messages.map((m, i) => (
          <div key={i} className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
            m.role === "user" ? "ml-auto bg-sky-900/50 text-sky-50" : "mr-auto bg-slate-800/70 text-slate-100"
          }`}>
            <div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">
              {m.role === "user" ? t("chat_you") : t("chat_mentor")}
            </div>
            <p className="whitespace-pre-line">{m.content}</p>
          </div>
        ))}
        {loading && <div className="text-xs text-slate-500">{t("chat_thinking")}</div>}
      </div>

      {lastSources.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-500">{t("chat_sources")}</span>
          {lastSources.map((id) => <SourcePill key={id} id={id} />)}
        </div>
      )}

      {messages.length > 0 && (
        <IncidentReportButton
          messages={messages}
          logContext={logContext}
          disabled={loading}
        />
      )}

      {error && (
        <div className="rounded border border-rose-700 bg-rose-950/40 p-3 text-xs text-rose-300">
          <strong>{t("alerts_error")}</strong> {error}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <button type="button" onClick={() => setShowLogContext((v) => !v)}
          className="self-start text-xs text-slate-400 hover:text-slate-200">
          {showLogContext ? "▼" : "▶"} {t("chat_log_context_toggle")}
        </button>
        {showLogContext && (
          <textarea value={logContext} onChange={(e) => setLogContext(e.target.value)}
            rows={4} placeholder={t("chat_log_context_placeholder")}
            className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-2 font-mono text-xs" />
        )}
        <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder={t("chat_input_placeholder")} disabled={loading}
            className="flex-1 rounded bg-slate-900 border border-slate-700 px-3 py-2 text-sm" />
          <button type="submit" disabled={loading || !input.trim()}
            className="rounded bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 text-sm font-medium text-white">
            {t("chat_send_btn")}
          </button>
        </form>
      </div>
    </div>
  );
}
