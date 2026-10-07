"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ApiError, forgotPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function ForgotInner() {
  const params = useSearchParams();
  const { t } = useI18n();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    setDevLink(null);
    try {
      const r = await forgotPassword(email.trim());
      setMessage(r.message);
      setDevLink(r.reset_link_dev);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Demasiadas solicitudes. Espera unos minutos.");
      } else if (err instanceof ApiError && err.status === 422) {
        setError("Email no válido.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md space-y-4 rounded-lg border border-slate-800 bg-slate-900/40 p-6"
      >
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("forgot_title")}</h1>
          <p className="text-sm text-slate-400 mt-1">{t("forgot_intro")}</p>
        </div>

        <label className="block text-sm">
          <span className="text-slate-400">{t("login_email")}</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
            autoComplete="email"
            className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2"
          />
        </label>

        {message && (
          <div className="rounded border border-emerald-700 bg-emerald-950/40 p-3 text-xs text-emerald-200">
            {message}
          </div>
        )}
        {devLink && (
          <div className="rounded border border-amber-700 bg-amber-950/40 p-3 text-xs text-amber-200 break-all">
            {t("forgot_dev_link")}:{" "}
            <a href={devLink} className="underline">
              {devLink}
            </a>
          </div>
        )}
        {error && (
          <div className="rounded border border-rose-700 bg-rose-950/40 p-3 text-xs text-rose-300">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy || !email.trim()}
          className="w-full rounded bg-sky-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white"
        >
          {busy ? t("forgot_sending") : t("forgot_send")}
        </button>

        <Link href="/login" className="block text-center text-xs text-slate-400 hover:text-slate-200">
          {t("forgot_back")}
        </Link>
      </form>
    </main>
  );
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<main className="min-h-screen p-8" />}>
      <ForgotInner />
    </Suspense>
  );
}
