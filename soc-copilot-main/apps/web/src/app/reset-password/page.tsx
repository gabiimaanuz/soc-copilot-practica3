"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, resetPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
  loadZxcvbn,
  MIN_STRENGTH_SCORE,
  PASSWORD_RULES,
  STRENGTH_COLORS,
  STRENGTH_LABELS,
  type ZxcvbnFn,
} from "@/lib/password";

function ResetInner() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const { t } = useI18n();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<"form" | "ok" | "invalid">(token ? "form" : "invalid");
  const [error, setError] = useState<string | null>(null);
  const [score, setScore] = useState(0);
  const zxcvbnRef = useRef<ZxcvbnFn | null>(null);

  useEffect(() => {
    loadZxcvbn().then((fn) => {
      zxcvbnRef.current = fn;
    });
  }, []);

  useEffect(() => {
    setScore(pw && zxcvbnRef.current ? zxcvbnRef.current(pw).score : 0);
  }, [pw]);

  const rules = useMemo(() => PASSWORD_RULES.map((r) => ({ ...r, ok: r.test(pw) })), [pw]);
  const matches = pw.length > 0 && pw === pw2;
  const canSubmit = rules.every((r) => r.ok) && score >= MIN_STRENGTH_SCORE && matches;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, pw);
      setState("ok");
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) setState("invalid");
      else if (err instanceof ApiError && err.status === 422) setError("La contraseña no cumple los requisitos.");
      else if (err instanceof ApiError && err.status === 429) setError("Demasiados intentos. Espera un minuto.");
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const card = "w-full max-w-md space-y-4 rounded-lg border border-slate-800 bg-slate-900/40 p-6";

  if (state === "ok" || state === "invalid") {
    const ok = state === "ok";
    return (
      <main className="min-h-screen flex items-center justify-center p-8">
        <div className={card}>
          <h1 className="text-2xl font-bold tracking-tight">{t("reset_title")}</h1>
          <div
            className={
              "rounded border p-3 text-sm " +
              (ok
                ? "border-emerald-700 bg-emerald-950/40 text-emerald-200"
                : "border-rose-700 bg-rose-950/40 text-rose-300")
            }
          >
            {ok ? t("reset_ok") : token ? t("reset_invalid") : t("reset_no_token")}
          </div>
          <Link
            href={ok ? "/login" : "/forgot-password"}
            className="inline-block rounded bg-sky-600 hover:brightness-110 px-4 py-2 text-sm font-medium text-white"
          >
            {ok ? t("reset_go_login") : t("reset_request_new")}
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <form onSubmit={onSubmit} className={card}>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("reset_title")}</h1>
          <p className="text-sm text-slate-400 mt-1">{t("reset_intro")}</p>
        </div>

        <label className="block text-sm">
          <span className="text-slate-400">{t("reset_new")}</span>
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            required
            minLength={10}
            autoFocus
            autoComplete="new-password"
            className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2"
          />
        </label>

        {pw && (
          <div className="space-y-2">
            <div className="flex gap-1">
              {[0, 1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className={`h-1.5 flex-1 rounded ${i <= score ? STRENGTH_COLORS[score] : "bg-slate-800"}`}
                />
              ))}
            </div>
            <p className="text-[11px] text-slate-400">
              Fortaleza: <span className="font-medium text-slate-200">{STRENGTH_LABELS[score]}</span>
            </p>
            <ul className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
              {rules.map((r) => (
                <li key={r.id} className={r.ok ? "text-emerald-400" : "text-slate-500"}>
                  {r.ok ? "✓" : "○"} {r.label}
                </li>
              ))}
            </ul>
          </div>
        )}

        <label className="block text-sm">
          <span className="text-slate-400">{t("reset_confirm")}</span>
          <input
            type="password"
            value={pw2}
            onChange={(e) => setPw2(e.target.value)}
            required
            minLength={10}
            autoComplete="new-password"
            className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2"
          />
          {pw2 && !matches && (
            <span className="mt-1 block text-[11px] text-rose-400">✕ {t("reset_mismatch")}</span>
          )}
        </label>

        {error && (
          <div className="rounded border border-rose-700 bg-rose-950/40 p-3 text-xs text-rose-300">{error}</div>
        )}

        <button
          type="submit"
          disabled={busy || !canSubmit}
          className="w-full rounded bg-sky-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white"
        >
          {busy ? t("reset_saving") : t("reset_btn")}
        </button>

        <Link href="/login" className="block text-center text-xs text-slate-400 hover:text-slate-200">
          {t("forgot_back")}
        </Link>
      </form>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<main className="min-h-screen p-8" />}>
      <ResetInner />
    </Suspense>
  );
}
