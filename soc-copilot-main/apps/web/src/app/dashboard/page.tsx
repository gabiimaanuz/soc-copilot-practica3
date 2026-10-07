"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell,
  Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { getStats, type StatsResponse } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";

// Colores de las gráficas por tema (Recharts necesita valores literales,
// no clases de Tailwind). Mismos tonos que la paleta de globals.css.
const CHART = {
  dark: {
    accent: "#22d3ee", grid: "#26334d", axis: "#8391a7", axisStrong: "#9aa8bc",
    tooltip: { background: "#101a2e", border: "1px solid #2c3a56", color: "#e2e8f0" },
    cursor: "rgba(34,211,238,0.08)",
    risk: { low: "#22c55e", medium: "#eab308", high: "#f97316", critical: "#ef4444", unknown: "#64748b" },
  },
  light: {
    accent: "#0e7490", grid: "#e2e8f0", axis: "#5b6b80", axisStrong: "#475569",
    tooltip: { background: "#ffffff", border: "1px solid #d3dbe6", color: "#0f172a" },
    cursor: "rgba(14,116,144,0.08)",
    risk: { low: "#16a34a", medium: "#ca8a04", high: "#ea580c", critical: "#dc2626", unknown: "#64748b" },
  },
} as const;
type ChartPalette = (typeof CHART)[keyof typeof CHART];

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={"rounded-xl border border-ink-700 bg-ink-900/60 p-5 " + className}>
      {children}
    </div>
  );
}

function KpiCard({ label, value, hint, accent, children }: {
  label: string; value: number | string; hint?: React.ReactNode;
  accent?: "danger" | "warn" | "ok"; children?: React.ReactNode;
}) {
  const valueClass = accent === "danger" ? "text-rose-400" : accent === "warn" ? "text-orange-400" : "text-slate-100";
  return (
    <Card className="hover:shadow-glow transition">
      <div className="text-[11px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <div className={`text-3xl font-semibold font-mono ${valueClass}`}>{value}</div>
        {hint && <div className="text-xs text-slate-400">{hint}</div>}
      </div>
      {children && <div className="mt-3">{children}</div>}
    </Card>
  );
}

function Sparkline({ data, color }: { data: { day: string; count: number }[]; color: string }) {
  if (!data.length) return <div className="h-8" />;
  const max = Math.max(1, ...data.map((d) => d.count));
  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * 100;
    const y = 30 - (d.count / max) * 26;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  return (
    <svg viewBox="0 0 100 30" className="w-full h-8" preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  );
}

function exportMitreCsv(rows: { technique: string; count: number }[]) {
  const lines = ["technique,count", ...rows.map((r) => `${r.technique},${r.count}`)];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "top-mitre.csv"; a.click();
  URL.revokeObjectURL(url);
}

export default function DashboardPage() {
  const auth = useRequireAuth();
  const { theme } = useTheme();
  const C: ChartPalette = CHART[theme];
  const RISK_COLORS: Record<string, string> = C.risk;
  const tooltipStyle = {
    ...C.tooltip,
    fontSize: "12px",
    borderRadius: "6px",
  };
  const { t } = useI18n();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Risk labels traducidos dinámicamente
  const RISK_LABEL: Record<string, string> = {
    low: t("tile_alerts_desc").includes("triage") ? "Bajo" : "Low",
    medium: "Medium", high: "High", critical: "Critical", unknown: "Unknown",
  };

  useEffect(() => {
    if (!auth.user) return;
    getStats().then(setStats).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [auth.user]);

  const dailySeries = useMemo(() => {
    if (!stats) return [];
    const map = new Map(stats.daily_last_30d.map((p) => [p.day, p.count]));
    const out: { day: string; count: number }[] = [];
    const today = new Date(); today.setUTCHours(0, 0, 0, 0);
    for (let i = 29; i >= 0; i--) {
      const d = new Date(today); d.setUTCDate(today.getUTCDate() - i);
      const key = d.toISOString().slice(0, 10);
      out.push({ day: key.slice(5), count: map.get(key) ?? 0 });
    }
    return out;
  }, [stats]);

  const last24h = useMemo(() => dailySeries.slice(-1)[0]?.count ?? 0, [dailySeries]);
  const last7Total = useMemo(() => dailySeries.slice(-7).reduce((a, b) => a + b.count, 0), [dailySeries]);
  const prev7Total = useMemo(() => dailySeries.slice(-14, -7).reduce((a, b) => a + b.count, 0), [dailySeries]);
  const trend7 = prev7Total ? Math.round(((last7Total - prev7Total) / prev7Total) * 100) : null;
  const criticalCount = useMemo(() => stats?.by_risk.filter((b) => b.risk_level === "critical").reduce((a, b) => a + b.count, 0) ?? 0, [stats]);
  const highCount = useMemo(() => stats?.by_risk.filter((b) => b.risk_level === "high").reduce((a, b) => a + b.count, 0) ?? 0, [stats]);

  if (!auth.ready) return <div className="p-8 text-slate-500 text-sm">{t("alerts_loading")}</div>;

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
            {t("nav_dashboard")}
          </h1>
          <p className="text-sm text-slate-400">
            {t("tile_dashboard_desc")}
            {stats && (
              <span className="ml-1 text-slate-500">
                · {stats.scope === "all" ? t("home_modules") : t("home_welcome")}
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          {stats && stats.top_mitre.length > 0 && (
            <button type="button" onClick={() => exportMitreCsv(stats.top_mitre)}
              className="px-3 py-2 rounded-md text-xs border border-ink-700 bg-ink-850 hover:bg-ink-800 text-slate-300">
              Exportar MITRE CSV
            </button>
          )}
          <Link href="/alerts" className="px-3 py-2 rounded-md text-xs bg-cyan-500 text-ink-950 font-medium hover:bg-cyan-400">
            + {t("home_analyze_alert")}
          </Link>
        </div>
      </div>

      {error && (
        <Card className="border-rose-700 bg-rose-950/40">
          <div className="text-sm text-rose-300"><strong>{t("alerts_error")}</strong> {error}</div>
        </Card>
      )}

      {!stats && !error && <p className="text-slate-400 text-sm">{t("history_loading")}</p>}

      {stats && stats.totals.alerts === 0 && (
        <Card>
          <p className="text-sm text-slate-400">
            Aún no hay datos. Crea tu primera alerta y vuelve aquí para ver las gráficas.
          </p>
        </Card>
      )}

      {stats && stats.totals.alerts > 0 && (
        <>
          {/* KPIs */}
          <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <KpiCard label={t("nav_alerts")} value={stats.totals.alerts}>
              <Sparkline data={dailySeries} color={C.accent} />
            </KpiCard>
            <KpiCard
              label="24 h"
              value={last24h}
              accent={last24h > 10 ? "danger" : last24h > 5 ? "warn" : undefined}
            />
            <KpiCard
              label="7 días"
              value={last7Total}
              hint={trend7 !== null ? (
                <span className={trend7 > 0 ? "text-rose-400" : "text-emerald-400"}>
                  {trend7 > 0 ? "▲" : "▼"} {Math.abs(trend7)}%
                </span>
              ) : undefined}
            />
            <KpiCard
              label="Critical"
              value={criticalCount}
              accent={criticalCount > 0 ? "danger" : "ok"}
            />
          </section>

          {/* Timeline + Copilot summary */}
          <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-2">
              <h2 className="text-sm font-semibold text-slate-200 mb-3">
                {t("tile_dashboard_desc")} — 30d
              </h2>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={dailySeries}>
                    <defs>
                      <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={C.accent} stopOpacity={0.3} />
                        <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                    <XAxis dataKey="day" stroke={C.axis} fontSize={11} interval="preserveStartEnd" />
                    <YAxis stroke={C.axis} fontSize={11} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: C.tooltip.color }} itemStyle={{ color: C.tooltip.color }} />
                    <Area type="monotone" dataKey="count" stroke={C.accent} strokeWidth={2} fill="url(#grad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card className="border-violet-500/30 bg-gradient-to-br from-violet-500/10 to-cyan-500/5 relative overflow-hidden">
              <div className="absolute -right-6 -top-6 w-24 h-24 rounded-full bg-violet-500/20 blur-2xl pointer-events-none" />
              <div className="flex items-center gap-2 mb-3">
                <span className="w-6 h-6 rounded-md bg-violet-500/30 grid place-items-center text-violet-300">✦</span>
                <h2 className="text-sm font-semibold text-slate-100">SOC Copilot</h2>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">
                <span className="text-rose-300 font-medium">{criticalCount} {t("tile_alerts_title")}</span>{" "}
                critical · {highCount} high.
                {stats.top_mitre[0] && (
                  <> Top: <span className="font-mono text-slate-200">{stats.top_mitre[0].technique}</span> ({stats.top_mitre[0].count}).</>
                )}
              </p>
              <div className="mt-3 flex gap-2">
                <Link href="/respond" className="text-[11px] px-2.5 py-1.5 rounded-md bg-cyan-500 text-ink-950 font-medium hover:bg-cyan-400">
                  {t("respond_title")}
                </Link>
                <Link href="/chat" className="text-[11px] px-2.5 py-1.5 rounded-md border border-ink-700 text-slate-300 hover:bg-ink-800">
                  {t("chat_title")}
                </Link>
              </div>
              <div className="mt-3 text-[10px] text-slate-500 font-mono">
                scope: {stats.scope} · base: {stats.totals.alerts}
              </div>
            </Card>
          </section>

          {/* Risk distribution + MITRE */}
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <h2 className="text-sm font-semibold text-slate-200 mb-3">{t("history_col_risk")}</h2>
              <div className="grid grid-cols-2 gap-4 items-center">
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={stats.by_risk} dataKey="count" nameKey="risk_level" innerRadius={45} outerRadius={75} paddingAngle={2}>
                        {stats.by_risk.map((b) => (
                          <Cell key={b.risk_level} fill={RISK_COLORS[b.risk_level] ?? C.risk.unknown} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: C.tooltip.color }} itemStyle={{ color: C.tooltip.color }} />
                      <Legend wrapperStyle={{ fontSize: "11px" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <ul className="text-xs space-y-1.5">
                  {stats.by_risk.map((b) => (
                    <li key={b.risk_level} className="flex justify-between items-center">
                      <span className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ background: RISK_COLORS[b.risk_level] ?? C.risk.unknown }} />
                        {RISK_LABEL[b.risk_level] ?? b.risk_level}
                      </span>
                      <span className="font-mono text-slate-300">{b.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>

            <Card>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-200">{t("alerts_mitre")}</h2>
                <span className="text-[11px] text-slate-500 font-mono">{stats.top_mitre.length}</span>
              </div>
              {stats.top_mitre.length === 0 ? (
                <p className="text-sm text-slate-500">Sin técnicas MITRE detectadas.</p>
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={stats.top_mitre} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                      <XAxis type="number" stroke={C.axis} fontSize={11} allowDecimals={false} />
                      <YAxis type="category" dataKey="technique" stroke={C.axisStrong} fontSize={11} width={80} />
                      <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: C.tooltip.color }} itemStyle={{ color: C.tooltip.color }} cursor={{ fill: C.cursor }} />
                      <Bar dataKey="count" fill={C.accent} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </section>

          {/* Por usuario */}
          {stats.scope === "all" && stats.by_user && stats.by_user.length > 0 && (
            <Card>
              <h2 className="text-sm font-semibold text-slate-200 mb-3">{t("nav_admin")} — {t("nav_alerts")}</h2>
              <table className="w-full text-sm">
                <thead className="text-left text-[10px] uppercase tracking-widest text-slate-500">
                  <tr>
                    <th className="px-3 py-2">{t("login_email")}</th>
                    <th className="px-3 py-2 text-right">{t("nav_alerts")}</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_user.map((u) => (
                    <tr key={u.user_id} className="border-t border-ink-700">
                      <td className="px-3 py-2 text-slate-300 font-mono text-xs">{u.email}</td>
                      <td className="px-3 py-2 text-right text-slate-200 font-mono">{u.alerts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <div className="text-[11px] text-slate-600 font-mono pt-4 border-t border-ink-800 flex justify-between">
            <span>SOC Copilot · Blue Team practice · 2026</span>
            <span>scope: {stats.scope}</span>
          </div>
        </>
      )}
    </div>
  );
}
