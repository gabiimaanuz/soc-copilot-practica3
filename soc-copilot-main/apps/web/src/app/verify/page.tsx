"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ApiError, verifyEmail } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function VerifyInner() {
  const params = useSearchParams();
  const { t } = useI18n();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"pending" | "ok" | "error">("pending");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setMessage("Falta el token en la URL.");
      return;
    }
    verifyEmail(token)
      .then(() => {
        setState("ok");
        setMessage("Email verificado. Ya puedes iniciar sesión.");
      })
      .catch((err) => {
        setState("error");
        if (err instanceof ApiError) setMessage(err.detail.slice(0, 200));
        else setMessage(err instanceof Error ? err.message : String(err));
      });
  }, [token]);

  const tone =
    state === "ok"
      ? "border-emerald-700 bg-emerald-950/40 text-emerald-200"
      : state === "error"
        ? "border-rose-700 bg-rose-950/40 text-rose-200"
        : "border-slate-700 bg-slate-900/40 text-slate-200";

  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className={`w-full max-w-md space-y-4 rounded-lg border p-6 ${tone}`}>
        <h1 className="text-2xl font-bold tracking-tight">
          {t("login_email")} — {state === "pending" ? "…" : state === "ok" ? "✓" : "✕"}
        </h1>
        <p className="text-sm">{message || "Verificando…"}</p>
        <Link
          href="/login"
          className="inline-block rounded bg-sky-600 hover:brightness-110 px-4 py-2 text-sm font-medium text-white"
        >
          {t("login_btn")}
        </Link>
      </div>
    </main>
  );
}

export default function VerifyPage() {
  return (
    <Suspense fallback={<main className="min-h-screen p-8" />}>
      <VerifyInner />
    </Suspense>
  );
}
