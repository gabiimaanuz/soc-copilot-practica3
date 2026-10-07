"use client";

import Link from "next/link";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export default function Home() {
  const auth = useRequireAuth();
  const { t } = useI18n();

  if (auth.loading || !auth.user) {
    return <div className="p-8" />;
  }

  const fullName =
    [auth.user.name, auth.user.last_name].filter(Boolean).join(" ") ||
    auth.user.email;

  const TILES = [
    { href: "/alerts",  title: t("tile_alerts_title"),    desc: t("tile_alerts_desc"),    icon: "▲" },
    { href: "/logs",    title: t("tile_logs_title"),      desc: t("tile_logs_desc"),      icon: "≡" },
    { href: "/chat",    title: t("tile_chat_title"),      desc: t("tile_chat_desc"),      icon: "◐" },
    { href: "/history", title: t("tile_history_title"),   desc: t("tile_history_desc"),   icon: "◷" },
    { href: "/dashboard",title: t("tile_dashboard_title"),desc: t("tile_dashboard_desc"), icon: "▦" },
  ];

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-8">
      <section className="rounded-xl border border-ink-700 bg-gradient-to-br from-cyan-500/10 via-ink-900/60 to-violet-500/10 p-8 relative overflow-hidden">
        <div className="absolute -right-10 -top-10 w-48 h-48 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
        <div className="absolute -left-10 -bottom-10 w-48 h-48 rounded-full bg-violet-500/10 blur-3xl pointer-events-none" />
        <div className="relative">
          <div className="text-[11px] uppercase tracking-widest text-cyan-300/80 mb-2">
            {t("home_welcome")}
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-100">
            {t("home_hello")}, {fullName.split(" ")[0]} <span className="text-cyan-300">.</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-xl">
            {t("home_subtitle")}
          </p>
          <div className="mt-4 flex gap-2">
            <Link
              href="/dashboard"
              className="px-3 py-2 rounded-md text-xs bg-cyan-500 text-ink-950 font-medium hover:bg-cyan-400"
            >
              {t("home_go_dashboard")}
            </Link>
            <Link
              href="/alerts"
              className="px-3 py-2 rounded-md text-xs border border-ink-700 bg-ink-850 hover:bg-ink-800 text-slate-300"
            >
              {t("home_analyze_alert")}
            </Link>
          </div>
        </div>
      </section>

      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-200">{t("home_modules")}</h2>
          <span className="text-[11px] text-slate-500 font-mono">
            {TILES.length + (auth.user.role === "admin" ? 1 : 0)} {t("home_available")}
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {TILES.map((tile) => (
            <Link
              key={tile.href}
              href={tile.href}
              className="group rounded-xl border border-ink-700 bg-ink-900/60 p-5 hover:border-cyan-500/40 hover:shadow-glow transition"
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-lg bg-ink-850 border border-ink-700 grid place-items-center text-cyan-300 group-hover:border-cyan-500/40">
                  {tile.icon}
                </div>
                <div className="flex-1">
                  <div className="font-medium text-slate-100 group-hover:text-cyan-300">
                    {tile.title}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                    {tile.desc}
                  </p>
                </div>
              </div>
            </Link>
          ))}
          {auth.user.role === "admin" && (
            <Link
              href="/admin"
              className="group rounded-xl border border-rose-500/30 bg-rose-500/5 p-5 hover:border-rose-500/60 transition"
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-lg bg-ink-850 border border-rose-500/30 grid place-items-center text-rose-300">
                  ◇
                </div>
                <div className="flex-1">
                  <div className="font-medium text-slate-100 group-hover:text-rose-300">
                    {t("tile_admin_title")}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                    {t("tile_admin_desc")}
                  </p>
                </div>
              </div>
            </Link>
          )}
        </div>
      </section>
    </div>
  );
}
