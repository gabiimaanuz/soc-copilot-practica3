"use client";

import { useEffect, useState } from "react";

import {
  ApiError,
  type MfaSetupResponse,
  type UserMe,
  mfaSetup,
  mfaVerify,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/** Shows recovery codes once, with copy / download. */
export function RecoveryCodes({
  codes,
  onContinue,
}: {
  codes: string[];
  onContinue?: () => void;
}) {
  const { t } = useI18n();
  const [saved, setSaved] = useState(false);
  const text = codes.join("\n");

  function download() {
    const blob = new Blob(
      [`SOC Copilot — recovery codes\n${new Date().toISOString()}\n\n${text}\n`],
      { type: "text/plain" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "soc-copilot-recovery-codes.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5_000);
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">{t("mfa_codes_title")}</h2>
      <p className="text-xs text-slate-400">{t("mfa_codes_intro")}</p>
      <ul className="grid grid-cols-2 gap-2 rounded border border-slate-700 bg-slate-950 p-3 font-mono text-sm">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="flex gap-2 text-xs">
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(text)}
          className="rounded border border-slate-700 px-3 py-1.5 hover:border-slate-500"
        >
          {t("mfa_codes_copy")}
        </button>
        <button
          type="button"
          onClick={download}
          className="rounded border border-slate-700 px-3 py-1.5 hover:border-slate-500"
        >
          {t("mfa_codes_download")}
        </button>
      </div>
      {onContinue && (
        <>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
            {t("mfa_codes_saved")}
          </label>
          <button
            type="button"
            disabled={!saved}
            onClick={onContinue}
            className="w-full rounded bg-sky-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white"
          >
            {t("mfa_continue")}
          </button>
        </>
      )}
    </div>
  );
}

/**
 * Second step of the login (Práctica 2 · MFA obligatorio).
 * mode="setup"  → QR enrolment + first code + recovery codes.
 * mode="verify" → TOTP or recovery code.
 */
export function MfaStep({
  mode,
  onDone,
  onCancel,
}: {
  mode: "setup" | "verify";
  onDone: (user: UserMe) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [setup, setSetup] = useState<MfaSetupResponse | null>(null);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [pending, setPending] = useState<{ user: UserMe; codes: string[] } | null>(null);

  useEffect(() => {
    if (mode !== "setup") return;
    mfaSetup()
      .then(setSetup)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) setExpired(true);
        else setError(e instanceof ApiError ? e.detail : String(e));
      });
  }, [mode]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await mfaVerify(
        useRecovery ? { recovery_code: code.trim() } : { code: code.replace(/\s/g, "") },
      );
      if (res.recovery_codes && res.recovery_codes.length > 0) {
        setPending({ user: res.user, codes: res.recovery_codes });
      } else {
        onDone(res.user);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401 && err.detail.includes("expired")) {
        setExpired(true);
      } else if (err instanceof ApiError && err.status === 429) {
        setError("429 — espera un minuto / wait a minute.");
      } else {
        setError(t("mfa_bad_code"));
      }
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (pending) {
    return <RecoveryCodes codes={pending.codes} onContinue={() => onDone(pending.user)} />;
  }

  if (expired) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-amber-300">{t("mfa_expired")}</p>
        <button type="button" onClick={onCancel} className="text-xs text-slate-300 hover:underline">
          {t("mfa_back")}
        </button>
      </div>
    );
  }

  const secretGroups = setup?.secret.match(/.{1,4}/g)?.join(" ") ?? "";

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">
          {mode === "setup" ? t("mfa_setup_title") : t("mfa_verify_title")}
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          {mode === "setup" ? t("mfa_setup_intro") : t("mfa_verify_intro")}
        </p>
      </div>

      {mode === "setup" && setup && (
        <div className="flex flex-col items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element -- inline SVG data URI */}
          <img
            src={setup.qr_svg_data_uri}
            alt="QR TOTP"
            width={200}
            height={200}
            className="rounded bg-white p-2"
          />
          <p className="text-[11px] text-slate-400">{t("mfa_manual_key")}</p>
          <code className="select-all rounded bg-slate-950 px-2 py-1 text-xs tracking-wider">
            {secretGroups}
          </code>
        </div>
      )}

      <label className="block text-sm">
        <span className="text-slate-400">
          {useRecovery ? t("mfa_recovery_label") : t("mfa_code_label")}
        </span>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          autoFocus
          autoComplete="one-time-code"
          inputMode={useRecovery ? "text" : "numeric"}
          pattern={useRecovery ? undefined : "[0-9 ]{6,7}"}
          maxLength={useRecovery ? 20 : 7}
          placeholder={useRecovery ? "xxxxx-xxxxx" : "123 456"}
          className="mt-1 w-full rounded bg-slate-900 border border-slate-700 px-3 py-2 font-mono tracking-widest"
        />
      </label>

      {error && (
        <div className="rounded border border-rose-700 bg-rose-950/40 p-3 text-xs text-rose-300">{error}</div>
      )}

      <button
        type="submit"
        disabled={busy || !code.trim() || (mode === "setup" && !setup)}
        className="w-full rounded bg-sky-600 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white"
      >
        {busy ? t("mfa_verifying") : t("mfa_verify_btn")}
      </button>

      <div className="flex justify-between text-xs">
        <button type="button" onClick={onCancel} className="text-slate-400 hover:text-slate-200">
          {t("mfa_back")}
        </button>
        {mode === "verify" && (
          <button
            type="button"
            onClick={() => {
              setUseRecovery((v) => !v);
              setCode("");
              setError(null);
            }}
            className="text-slate-400 hover:text-slate-200"
          >
            {useRecovery ? t("mfa_use_totp") : t("mfa_use_recovery")}
          </button>
        )}
      </div>
    </form>
  );
}
