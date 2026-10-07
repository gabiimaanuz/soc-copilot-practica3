"use client";

import { useEffect, useState } from "react";
import { ApiError, clearLLMKey, getLLMSettings, type LLMSettings, updateLLMSettings } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export default function LLMSettingsPage() {
  const auth = useRequireAuth();
  const { t } = useI18n();
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [model, setModel] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    if (!auth.ready || !auth.user) return;
    getLLMSettings()
      .then((s) => { setSettings(s); setModel(s.preferred_chat_model ?? s.default_model); })
      .catch((err) => setError(err instanceof ApiError ? err.detail : "No se pudo cargar la configuración de LLM"));
  }, [auth.ready, auth.user]);

  async function onSaveModel() {
    setBusy(true); setError(null); setInfo(null);
    try { const s = await updateLLMSettings({ preferred_chat_model: model }); setSettings(s); setInfo("Modelo predeterminado actualizado."); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "No se pudo guardar el modelo"); }
    finally { setBusy(false); }
  }

  async function onSaveKey(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setBusy(true); setError(null); setInfo(null);
    try { const s = await updateLLMSettings({ api_key: apiKey.trim() }); setSettings(s); setApiKey(""); setShowKey(false); setInfo("Clave validada y guardada cifrada."); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "No se pudo guardar la API key"); }
    finally { setBusy(false); }
  }

  async function onClearKey() {
    if (!confirm("¿Eliminar tu clave personal? Volverás a usar la del servidor.")) return;
    setBusy(true); setError(null); setInfo(null);
    try { const s = await clearLLMKey(); setSettings(s); setInfo("Clave eliminada. Volviste a la clave del servidor."); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "No se pudo eliminar la clave"); }
    finally { setBusy(false); }
  }

  if (!auth.ready) return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;
  if (!settings) return <div className="p-8 text-slate-500 text-sm">{error ?? "Cargando…"}</div>;

  const quotaPct = Math.min(100, Math.round((settings.server_quota_used / Math.max(1, settings.server_quota_limit)) * 100));

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">{t("settings_title")}</h1>
        <p className="text-slate-400 mt-2">{t("settings_subtitle")}</p>
      </header>

      {error && <div className="text-sm bg-rose-950/40 border border-rose-800 text-rose-300 p-3 rounded">{error}</div>}
      {info && <div className="text-sm bg-emerald-950/40 border border-emerald-800 text-emerald-300 p-3 rounded">{info}</div>}

      <section className="bg-ink-900/60 border border-ink-700 rounded-lg p-6 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("settings_default_model")}</h2>
          <p className="text-sm text-slate-400 mt-1">{t("settings_model_desc")}</p>
        </div>
        <select value={model} onChange={(e) => setModel(e.target.value)}
          className="w-full rounded bg-slate-950 border border-slate-700 px-3 py-2 text-slate-100">
          {settings.available_models.map((m) => (
            <option key={m} value={m}>{m} {m === settings.default_model ? "(servidor)" : ""}</option>
          ))}
        </select>
        <div className="flex justify-end">
          <button type="button" disabled={busy || model === (settings.preferred_chat_model ?? settings.default_model)} onClick={onSaveModel}
            className="px-4 py-2 text-sm bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed rounded font-medium text-white">
            {t("settings_save_model")}
          </button>
        </div>
      </section>

      <section className="bg-ink-900/60 border border-ink-700 rounded-lg p-6 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("settings_api_key")}</h2>
          <p className="text-sm text-slate-400 mt-1">
            Se guarda <strong>cifrada</strong> en el servidor. Genera una en{" "}
            <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">Google AI Studio</a>.
          </p>
        </div>
        {settings.configured ? (
          <div className="flex items-center justify-between bg-slate-950 border border-ink-700 rounded p-3">
            <div className="text-sm">
              <div className="text-slate-300">Clave configurada: <span className="font-mono">••••{settings.key_last4}</span></div>
              {settings.key_validated_at && <div className="text-xs text-slate-500 mt-1">Validada el {new Date(settings.key_validated_at).toLocaleString()}</div>}
            </div>
            <button type="button" disabled={busy} onClick={onClearKey}
              className="px-3 py-1.5 text-sm border border-rose-800 text-rose-300 hover:bg-rose-950/40 rounded">
              Eliminar clave
            </button>
          </div>
        ) : (
          <div className="text-sm bg-amber-950/30 border border-amber-900 text-amber-200 p-3 rounded">
            Estás usando la clave compartida del servidor.
            <div className="mt-2">
              Cuota diaria: {settings.server_quota_used} / {settings.server_quota_limit} llamadas
              <div className="h-1.5 bg-slate-800 rounded mt-1 overflow-hidden">
                <div className="h-full bg-amber-500" style={{ width: `${quotaPct}%` }} />
              </div>
            </div>
          </div>
        )}
        <form onSubmit={onSaveKey} className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-400">{settings.configured ? "Reemplazar clave" : "Pegar clave"}</span>
            <div className="flex gap-2 mt-1">
              <input type={showKey ? "text" : "password"} value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                placeholder="AIza..." autoComplete="off" spellCheck={false}
                className="flex-1 rounded bg-slate-950 border border-slate-700 px-3 py-2 text-slate-100 font-mono" />
              <button type="button" onClick={() => setShowKey((v) => !v)}
                className="px-3 py-2 text-sm border border-slate-700 rounded text-slate-300 hover:bg-slate-800">
                {showKey ? "Ocultar" : "Mostrar"}
              </button>
            </div>
          </label>
          <div className="flex justify-end">
            <button type="submit" disabled={busy || apiKey.trim().length < 10}
              className="px-4 py-2 text-sm bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed rounded font-medium text-white">
              {busy ? "Validando…" : "Validar y guardar"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
