"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { useI18n, type Locale, LOCALE_LABELS } from "@/lib/i18n";

type NavItem = {
  href: string;
  labelKey: string;
  icon: string;
  badge?: string;
  shortcut?: string;
};

const OPS_NAV: NavItem[] = [
  { href: "/dashboard", labelKey: "nav_dashboard", icon: "▦", shortcut: "⌘1" },
  { href: "/alerts",    labelKey: "nav_alerts",    icon: "▲" },
  { href: "/siem",      labelKey: "nav_siem",      icon: "⇶" },
  { href: "/logs",      labelKey: "nav_logs",      icon: "≡" },
  { href: "/chat",      labelKey: "nav_chat",      icon: "◐" },
  { href: "/history",   labelKey: "nav_history",   icon: "◷" },
];

const SYS_NAV: NavItem[] = [
  { href: "/settings/llm", labelKey: "nav_settings", icon: "⚙" },
  { href: "/admin",        labelKey: "nav_admin",     icon: "◇" },
];

function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const { t } = useI18n();

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  const sysNav = SYS_NAV.filter(
    (it) => it.href !== "/admin" || user?.role === "admin",
  );

  const renderItem = (it: NavItem) => {
    const active = isActive(it.href);
    return (
      <Link
        key={it.href}
        href={it.href}
        className={
          "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition " +
          (active
            ? "bg-cyan-500/10 text-cyan-300 border border-cyan-500/20"
            : "text-slate-300 hover:bg-ink-800 border border-transparent")
        }
      >
        <span className="w-4 text-center">{it.icon}</span>
        <span>{t(it.labelKey as Parameters<typeof t>[0])}</span>
        {it.badge && (
          <span className="ml-auto text-[10px] font-mono px-1.5 rounded bg-rose-500/20 text-rose-300">
            {it.badge}
          </span>
        )}
        {it.shortcut && !it.badge && active && (
          <span className="ml-auto text-[10px] font-mono text-cyan-300/70">
            {it.shortcut}
          </span>
        )}
      </Link>
    );
  };

  return (
    <aside className="sidebar w-64 shrink-0 border-r flex flex-col">
      <Link
        href="/"
        className="px-5 py-5 border-b flex items-center gap-3"
      >
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-cyan-500 to-violet-500 flex items-center justify-center text-ink-950 font-bold">
          S
        </div>
        <div>
          <div className="font-semibold tracking-tight">SOC Copilot</div>
          <div className="text-[11px] font-mono opacity-50">v0.4.2 · prod</div>
        </div>
      </Link>

      <nav className="px-3 py-4 space-y-1">
        <div className="px-3 pb-2 text-[10px] uppercase tracking-widest opacity-50">
          {t("nav_ops")}
        </div>
        {OPS_NAV.map(renderItem)}

        <div className="px-3 pt-5 pb-2 text-[10px] uppercase tracking-widest opacity-50">
          {t("nav_system")}
        </div>
        {sysNav.map(renderItem)}
      </nav>

      <div className="mt-auto m-3 rounded-lg border p-3 text-xs status-widget">
        <div className="flex items-center gap-2 mb-2">
          <span className="relative inline-block w-2 h-2 rounded-full bg-emerald-400 pulse-dot" />
          <span>{t("status_backend")}</span>
        </div>
        <div className="font-mono opacity-50 leading-5">
          api &nbsp; · 142 ms
          <br />
          chroma · 38 ms
          <br />
          gemini · ok
        </div>
      </div>
    </aside>
  );
}

function Topbar() {
  const { user, signOut } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useI18n();

  const initials = user
    ? `${(user.name?.[0] ?? user.email[0]).toUpperCase()}${
        user.last_name?.[0]?.toUpperCase() ?? ""
      }`
    : "?";
  const fullName = user
    ? [user.name, user.last_name].filter(Boolean).join(" ") || user.email
    : "";

  const locales: Locale[] = ["es", "en", "fr"];

  return (
    <header className="topbar h-14 border-b backdrop-blur flex items-center px-6 gap-4 sticky top-0 z-40">
      <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs w-96 search-box">
        <span>⌕</span>
        <input
          className="bg-transparent outline-none flex-1 placeholder:opacity-40"
          placeholder={t("topbar_search_placeholder")}
        />
        <span className="font-mono text-[10px] opacity-40">⌘K</span>
      </div>

      <div className="ml-auto flex items-center gap-3">
        {/* ── Language selector ─────────────────────────────── */}
        <div className="flex items-center rounded-md border overflow-hidden text-xs lang-selector">
          {locales.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLocale(l)}
              className={
                "px-2 py-1.5 font-medium transition " +
                (locale === l
                  ? "bg-cyan-500 text-ink-950"
                  : "opacity-50 hover:opacity-80")
              }
              title={LOCALE_LABELS[l]}
            >
              {l.toUpperCase()}
            </button>
          ))}
        </div>

        {/* ── Theme toggle ──────────────────────────────────── */}
        <button
          type="button"
          onClick={toggleTheme}
          className="rounded-md border px-2.5 py-1.5 text-xs font-medium transition hover:border-cyan-500/40 theme-toggle"
          title={theme === "dark" ? t("theme_light") : t("theme_dark")}
        >
          {theme === "dark" ? t("theme_light") : t("theme_dark")}
        </button>

        <Link
          href="/settings/llm"
          className="text-xs flex items-center gap-2 px-3 py-1.5 rounded-md border hover:border-cyan-500/30 model-btn"
          title="Configuración del modelo"
        >
          <span className="opacity-50">{t("topbar_model")}</span>
          <span className="text-cyan-300 font-medium">gemini-3.5-flash-lite</span>
          <span className="opacity-40">▾</span>
        </Link>

        {user && (
          <>
            <span
              className={
                "px-1.5 py-0.5 rounded text-[10px] font-medium uppercase border " +
                (user.role === "admin"
                  ? "bg-rose-500/10 text-rose-300 border-rose-500/30"
                  : "bg-cyan-500/10 text-cyan-300 border-cyan-500/30")
              }
            >
              {user.role}
            </span>
            <span
              className={
                "px-1.5 py-0.5 rounded text-[10px] font-medium uppercase border " +
                (user.level === "INSTRUCTOR"
                  ? "bg-violet-500/10 text-violet-300 border-violet-500/30"
                  : user.level === "L2"
                    ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                    : "bg-amber-500/10 text-amber-300 border-amber-500/30")
              }
              title="Nivel SOC — ajusta el tono del Copilot (editable en Mi Perfil)"
            >
              {user.level}
            </span>
            <Link
              href="/profile"
              className="flex items-center gap-2 pl-3 border-l group"
            >
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-500 to-violet-500 grid place-items-center text-xs font-bold text-ink-950">
                {initials}
              </div>
              <div className="text-xs leading-tight">
                <div className="group-hover:text-cyan-300">{fullName}</div>
                <div className="opacity-40">
                  {user.role} · {user.email}
                </div>
              </div>
            </Link>
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-md border px-2.5 py-1.5 text-xs transition hover:border-slate-500"
              title="Cerrar sesión"
            >
              {t("topbar_signout")}
            </button>
          </>
        )}
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();

  if (pathname === "/login" || !user) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen grid-bg">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
