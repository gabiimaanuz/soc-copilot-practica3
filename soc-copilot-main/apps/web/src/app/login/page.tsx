"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { MfaStep } from "@/components/MfaStep";
import { ApiError, checkEmail, register, UserLevel } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import {
  loadZxcvbn, MIN_STRENGTH_SCORE, PASSWORD_RULES,
  STRENGTH_COLORS, STRENGTH_LABELS, type ZxcvbnFn,
} from "@/lib/password";

const LEVEL_OPTIONS: { value: UserLevel; label: string; hint: string }[] = [
  { value: "L1", label: "Analista L1", hint: "Junior — el Copilot explica paso a paso" },
  { value: "L2", label: "Analista L2", hint: "Senior — respuestas más concisas" },
  { value: "INSTRUCTOR", label: "Instructor", hint: "Detalle completo sin filtros" },
];

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const auth = useAuth();
  const { t } = useI18n();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [level, setLevel] = useState<UserLevel>("L1");
  const [website, setWebsite] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  // Práctica 2 · MFA obligatorio: second step after a correct password.
  const [mfaStep, setMfaStep] = useState<"setup" | "verify" | null>(null);

  const [strengthScore, setStrengthScore] = useState(0);
  const [strengthFeedback, setStrengthFeedback] = useState<string>("");
  const zxcvbnRef = useRef<ZxcvbnFn | null>(null);

  useEffect(() => {
    if (mode !== "register" || zxcvbnRef.current) return;
    loadZxcvbn().then((fn) => {
      zxcvbnRef.current = fn;
      if (password) { const r = fn(password); setStrengthScore(r.score); setStrengthFeedback(r.feedback.warning || r.feedback.suggestions[0] || ""); }
    });
  }, [mode, password]);

  useEffect(() => {
    if (mode !== "register" || !zxcvbnRef.current || !password) { setStrengthScore(0); setStrengthFeedback(""); return; }
    const r = zxcvbnRef.current(password);
    setStrengthScore(r.score);
    setStrengthFeedback(r.feedback.warning || r.feedback.suggestions[0] || "");
  }, [password, mode]);

  const [emailStatus, setEmailStatus] = useState<"idle"|"checking"|"available"|"taken"|"invalid">("idle");
  useEffect(() => {
    if (mode !== "register" || !email) { setEmailStatus("idle"); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setEmailStatus("invalid"); return; }
    setEmailStatus("checking");
    const handle = setTimeout(async () => {
      try { const r = await checkEmail(email); setEmailStatus(r.available ? "available" : "taken"); }
      catch { setEmailStatus("idle"); }
    }, 350);
    return () => clearTimeout(handle);
  }, [email, mode]);

  useEffect(() => { if (!auth.loading && auth.user) router.replace(next); }, [auth.loading, auth.user, next, router]);

  const ruleChecks = useMemo(() => PASSWORD_RULES.map((r) => ({ ...r, ok: r.test(password) })), [password]);
  const allRulesPass = ruleChecks.every((r) => r.ok);
  const passwordsMatch = password.length > 0 && password === passwordConfirm;
  const canSubmit = mode === "login"
    ? email.length > 0 && password.length > 0
    : name.length >= 2 && emailStatus === "available" && allRulesPass && strengthScore >= MIN_STRENGTH_SCORE && passwordsMatch;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError(null); setInfo(null);
    try {
      if (mode === "register") {
        const r = await register(email, password, name, level, website);
        if (r.verification_required) {
          setInfo(r.verification_link_dev
            ? `Cuenta creada. Verifica tu email: ${r.verification_link_dev}`
            : "Cuenta creada. Revisa tu email para verificarla antes de iniciar sesión.");
          setMode("login"); setPassword(""); setPasswordConfirm(""); return;
        }
      }
      const res = await auth.signIn(email, password);
      if (res.mfa_required) {
        setPassword("");
        setPasswordConfirm("");
        setMfaStep(res.mfa_setup_required ? "setup" : "verify");
        return;
      }
      router.replace(next);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) setError("Credenciales inválidas.");
        else if (err.status === 403) setError(mode === "register" ? "El registro está cerrado temporalmente." : "Acceso denegado. ¿Tienes el email verificado?");
        else if (err.status === 409) setError("Ese email ya está registrado.");
        else if (err.status === 422) setError("Datos inválidos. Revisa los requisitos.");
        else if (err.status === 429) setError("Demasiados intentos. Espera un minuto.");
        else setError(err.detail.slice(0, 200));
      } else { setError(err instanceof Error ? err.message : String(err)); }
    } finally { setLoading(false); }
  }

  if (mfaStep) {
    return (
      <main className="min-h-screen flex items-center justify-center p-8">
        <div className="w-full max-w-md rounded-lg border border-slate-800 bg-slate-900/40 p-6">
          <MfaStep
            mode={mfaStep}
            onDone={(u) => {
              auth.completeSignIn(u);
              router.replace(next);
            }}
            onCancel={() => {
              setMfaStep(null);
              setMode("login");
            }}
          />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <form onSubmit={onSubmit} className="w-full max-w-md space-y-4 rounded-lg border border-slate-800 bg-slate-900/40 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("login_title")}</h1>
          <p className="text-sm text-slate-400 mt-1">
            {mode === "login" ? t("login_subtitle") : t("login_register_subtitle")}
          </p>
        </div>

        {mode === "register" && (
          <>
            <div aria-hidden="true" style={{ position:"absolute",left:"-10000px",top:"auto",width:"1px",height:"1px",overflow:"hidden" }}>
              <label>Website<input type="text" name="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} /></label>
            </div>
            <label className="block text-sm">
              <span className="text-slate-400">{t("login_name")}</span>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} autoComplete="name"
                className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2" />
            </label>
            <fieldset className="block text-sm">
              <legend className="text-slate-400 mb-1">{t("login_level")}</legend>
              <div className="grid grid-cols-3 gap-2">
                {LEVEL_OPTIONS.map((opt) => (
                  <label key={opt.value} className={`cursor-pointer rounded border px-2 py-2 text-center ${level === opt.value ? "border-sky-500 bg-sky-950/40" : "border-slate-700 hover:border-slate-500"}`} title={opt.hint}>
                    <input type="radio" name="level" value={opt.value} checked={level === opt.value} onChange={() => setLevel(opt.value)} className="sr-only" />
                    <span className="block text-xs font-medium">{opt.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        )}

        <label className="block text-sm">
          <span className="text-slate-400">{t("login_email")}</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email"
            className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2" />
          {mode === "register" && email && (
            <span className={`mt-1 block text-[11px] ${emailStatus === "available" ? "text-emerald-400" : emailStatus === "taken" ? "text-rose-400" : "text-slate-500"}`}>
              {emailStatus === "checking" && "Comprobando…"}
              {emailStatus === "available" && "✓ Email disponible"}
              {emailStatus === "taken" && "✕ Email ya registrado"}
              {emailStatus === "invalid" && "Formato inválido"}
            </span>
          )}
        </label>

        <label className="block text-sm">
          <span className="text-slate-400">{t("login_password")}</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
            minLength={mode === "register" ? 10 : 1} autoComplete={mode === "register" ? "new-password" : "current-password"}
            className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2" />
        </label>

        {mode === "login" && (
          <div className="-mt-2 text-right">
            <Link
              href={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`}
              className="text-xs text-cyan-400 hover:underline"
            >
              {t("forgot_link")}
            </Link>
          </div>
        )}

        {mode === "register" && (
          <label className="block text-sm">
            <span className="text-slate-400">{t("login_confirm_password")}</span>
            <input type="password" value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} required minLength={10} autoComplete="new-password"
              className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2" />
            {passwordConfirm && (
              <span className={`mt-1 block text-[11px] ${passwordsMatch ? "text-emerald-400" : "text-rose-400"}`}>
                {passwordsMatch ? "✓ Las contraseñas coinciden" : "✕ Las contraseñas no coinciden"}
              </span>
            )}
          </label>
        )}

        {mode === "register" && password && (
          <div className="space-y-2">
            <div className="flex gap-1">
              {[0,1,2,3,4].map((i) => (
                <div key={i} className={`h-1.5 flex-1 rounded ${i <= strengthScore ? STRENGTH_COLORS[strengthScore] : "bg-slate-800"}`} />
              ))}
            </div>
            <p className="text-[11px] text-slate-400">Fortaleza: <span className="font-medium text-slate-200">{STRENGTH_LABELS[strengthScore]}</span>{strengthFeedback ? ` — ${strengthFeedback}` : ""}</p>
            <ul className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
              {ruleChecks.map((r) => (
                <li key={r.id} className={r.ok ? "text-emerald-400" : "text-slate-500"}>{r.ok ? "✓" : "○"} {r.label}</li>
              ))}
            </ul>
          </div>
        )}

        {error && <div className="rounded border border-rose-700 bg-rose-950/40 p-3 text-xs text-rose-300">{error}</div>}
        {info && <div className="rounded border border-emerald-700 bg-emerald-950/40 p-3 text-xs text-emerald-200 break-all">{info}</div>}

        <button type="submit" disabled={loading || !canSubmit}
          className="w-full rounded bg-sky-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white">
          {loading ? t("login_loading_btn") : mode === "login" ? t("login_btn") : t("login_register_btn")}
        </button>

        <button type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); setInfo(null); setPasswordConfirm(""); }}
          className="block w-full text-center text-xs text-slate-400 hover:text-slate-200">
          {mode === "login" ? t("login_switch_to_register") : t("login_switch_to_login")}
        </button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="min-h-screen p-8" />}>
      <LoginInner />
    </Suspense>
  );
}
