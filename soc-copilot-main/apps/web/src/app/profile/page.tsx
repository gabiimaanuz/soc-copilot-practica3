"use client";

import { useEffect, useState } from "react";
import { RecoveryCodes } from "@/components/MfaStep";
import {
  ApiError,
  getMfaStatus,
  type MfaStatus,
  regenerateRecoveryCodes,
  updateProfile,
  UserLevel,
} from "@/lib/api";
import { useAuth, useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

const LEVEL_OPTIONS: { value: UserLevel; label: string; hint: string }[] = [
  { value: "L1", label: "Analista L1 (Junior)", hint: "El Copilot explica paso a paso, define siglas y sugiere el siguiente comando." },
  { value: "L2", label: "Analista L2 (Senior)", hint: "Respuestas concisas y técnicas, sin teoría básica." },
  { value: "INSTRUCTOR", label: "Instructor", hint: "Detalle completo: razonamiento alternativo, falsos positivos y ejemplos pedagógicos." },
];

function MfaSection() {
  const { t } = useI18n();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getMfaStatus().then(setStatus).catch(() => setStatus(null));
  }, [codes]);

  async function regen(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await regenerateRecoveryCodes(code.replace(/\s/g, ""));
      setCodes(r.recovery_codes);
      setCode("");
    } catch (err) {
      setError(err instanceof ApiError ? t("mfa_bad_code") : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;
  return (
    <section className="rounded-lg border border-ink-700 bg-ink-900/60 p-6 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("mfa_profile_title")}</h2>
        {status.enabled && (
          <span className="rounded border border-emerald-700 bg-emerald-900/40 px-2 py-0.5 text-xs text-emerald-300">
            {t("mfa_profile_on")}
          </span>
        )}
      </div>
      {status.enabled && (
        <p className="text-xs text-slate-400">
          TOTP · {t("mfa_profile_since")}{" "}
          {status.enabled_at ? new Date(status.enabled_at).toLocaleDateString() : "—"} ·{" "}
          {status.recovery_codes_left} {t("mfa_profile_left")}
        </p>
      )}
      {codes ? (
        <RecoveryCodes codes={codes} />
      ) : (
        status.enabled && (
          <form onSubmit={regen} className="space-y-2">
            <p className="text-xs text-slate-400">{t("mfa_profile_regen_hint")}</p>
            <div className="flex gap-2">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={7}
                placeholder="123 456"
                className="w-32 rounded bg-slate-900 border border-slate-700 px-3 py-2 font-mono text-sm"
              />
              <button
                type="submit"
                disabled={busy || code.replace(/\s/g, "").length !== 6}
                className="rounded bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-2 text-xs font-medium text-white"
              >
                {t("mfa_profile_regen")}
              </button>
            </div>
            {error && <p className="text-xs text-rose-300">{error}</p>}
          </form>
        )
      )}
      <p className="text-[11px] text-slate-500">{t("mfa_profile_lost")}</p>
    </section>
  );
}

export default function ProfilePage() {
  const auth = useRequireAuth();
  const { refresh } = useAuth();
  const { t } = useI18n();

  const [name, setName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [level, setLevel] = useState<UserLevel>("L1");
  const [currentPassword, setCurrentPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (auth.user) {
      setName(auth.user.name);
      setLastName(auth.user.last_name ?? "");
      setEmail(auth.user.email);
      setLevel(auth.user.level);
    }
  }, [auth.user]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!auth.user) return;
    setSaving(true); setError(null); setSuccess(false);
    try {
      const emailChanging = email !== auth.user.email;
      await updateProfile({
        name: name !== auth.user.name ? name : undefined,
        last_name: lastName !== (auth.user.last_name ?? "") ? lastName : undefined,
        email: emailChanging ? email : undefined,
        level: level !== auth.user.level ? level : undefined,
        current_password: emailChanging ? currentPassword : undefined,
      });
      await refresh();
      setCurrentPassword(""); setSuccess(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "No se pudo guardar el perfil");
    } finally { setSaving(false); }
  }

  if (!auth.ready) return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;

  const u = auth.user!;
  const canEditLevel = u.role === "admin";
  const dirty = name !== u.name || lastName !== (u.last_name ?? "") || email !== u.email || (canEditLevel && level !== u.level);
  const levelHint = LEVEL_OPTIONS.find((o) => o.value === level)?.hint;
  const requestedHint = !canEditLevel && !u.level_approved && u.requested_level !== u.level
    ? `Solicitaste ${u.requested_level}; un administrador revisará y asignará tu nivel definitivo.` : null;

  return (
    <div className="p-6 max-w-xl mx-auto space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">{t("profile_title")}</h1>
        <p className="text-slate-400 mt-2">{t("profile_subtitle")}</p>
      </header>

      <section className="bg-ink-900/60 border border-ink-700 rounded-lg p-6 space-y-4">
        {error && <div className="text-sm bg-rose-950/40 border border-rose-800 text-rose-300 p-3 rounded">{error}</div>}
        {success && !dirty && <div className="text-sm bg-emerald-950/40 border border-emerald-800 text-emerald-300 p-3 rounded">Perfil actualizado correctamente.</div>}

        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block text-sm">
            <span className="text-slate-400">{t("profile_name")}</span>
            <input type="text" required minLength={2} maxLength={100} value={name} onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded bg-slate-950 border border-slate-700 px-3 py-2 text-slate-100" />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">{t("profile_lastname")}</span>
            <input type="text" maxLength={100} value={lastName} onChange={(e) => setLastName(e.target.value)}
              className="mt-1 w-full rounded bg-slate-950 border border-slate-700 px-3 py-2 text-slate-100" placeholder="Opcional" />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">{t("profile_email")}</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded bg-slate-950 border border-slate-700 px-3 py-2 text-slate-100" />
          </label>
          {email !== u.email && (
            <label className="block text-sm">
              <span className="text-slate-400">Contraseña actual</span>
              <input type="password" required value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)}
                className="mt-1 w-full rounded bg-slate-950 border border-slate-700 px-3 py-2 text-slate-100" />
            </label>
          )}

          <fieldset className="border border-ink-700 rounded-lg p-4 space-y-2">
            <legend className="px-2 text-sm text-slate-300">Nivel SOC</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {LEVEL_OPTIONS.map((opt) => {
                const selected = level === opt.value;
                return (
                  <label key={opt.value} className={`rounded border px-3 py-2 text-sm transition-colors ${selected ? "border-cyan-500 bg-cyan-500/10 text-cyan-200" : "border-ink-700 bg-ink-950 text-slate-300"} ${canEditLevel ? "cursor-pointer hover:border-ink-600" : "cursor-not-allowed opacity-70"}`}>
                    <input type="radio" name="level" value={opt.value} checked={selected} disabled={!canEditLevel} onChange={() => setLevel(opt.value)} className="sr-only" />
                    {opt.label}
                  </label>
                );
              })}
            </div>
            {levelHint && <p className="text-[11px] text-slate-400">{levelHint}</p>}
            {requestedHint && <p className="text-[11px] text-amber-300">{requestedHint}</p>}
          </fieldset>

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" disabled={!dirty || saving}
              onClick={() => { setName(u.name); setLastName(u.last_name ?? ""); setEmail(u.email); setLevel(u.level); setSuccess(false); setError(null); }}
              className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 disabled:opacity-40">
              {t("profile_discard")}
            </button>
            <button type="submit" disabled={!dirty || saving}
              className="px-4 py-2 text-sm bg-cyan-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed rounded font-medium text-white">
              {saving ? t("profile_saving") : t("profile_save")}
            </button>
          </div>
        </form>
      </section>

      <MfaSection />
    </div>
  );
}
