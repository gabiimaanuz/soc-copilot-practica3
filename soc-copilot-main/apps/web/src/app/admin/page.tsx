"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  AdminUserView,
  ApiError,
  AppSettingsView,
  AuditLogEntry,
  PermissionCell,
  PermissionChange,
  UserLevel,
  UserRole,
  adminChangeLevel,
  adminChangePassword,
  adminChangeRole,
  adminCreateUser,
  adminDeleteUser,
  adminResetLlmQuota,
  adminResetMfa,
  getAdminUsers,
  getAppSettings,
  getAuditLog,
  getPermissions,
  setPublicRegistrationEnabled,
  updatePermissions,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import {
  evaluatePassword,
  loadZxcvbn,
  MIN_STRENGTH_SCORE,
  STRENGTH_COLORS,
  STRENGTH_LABELS,
  type ZxcvbnFn,
} from "@/lib/password";

type Tab = "usuarios" | "roles" | "permisos" | "auditoria";

const AUDIT_PAGE_SIZE = 100;
const ACTION_OPTIONS = [
  "",
  "user.create",
  "user.delete",
  "user.role_change",
  "user.password_reset",
] as const;

const ROLE_DESCRIPTIONS: Record<UserRole, { title: string; blurb: string }> = {
  analyst: {
    title: "Analyst",
    blurb:
      "Rol por defecto. Puede analizar logs, generar recomendaciones y consultar el chat con RAG. Solo ve sus propias alertas.",
  },
  admin: {
    title: "Admin",
    blurb:
      "Acceso completo. Gestiona usuarios, roles y contraseñas. Ve todas las alertas, incluidas las huérfanas (sin propietario).",
  },
};

// Capacidades baseline (no gated por backend; se aplican en código de los
// endpoints CurrentUser). Se muestran en la matriz como informativas.
const BASELINE_CAPS: { area: string; action: string }[] = [
  { area: "Alertas", action: "Crear / explicar alertas" },
  { area: "Alertas", action: "Listar propias" },
  { area: "Alertas", action: "Recomendar siguiente paso" },
  { area: "Chat", action: "Chat IA + RAG" },
  { area: "Logs", action: "Subir y filtrar archivos locales" },
];

export default function AdminPage() {
  const auth = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("usuarios");
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Password modal
  const [pwUser, setPwUser] = useState<AdminUserView | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [pwLoading, setPwLoading] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwStrengthScore, setPwStrengthScore] = useState(0);
  const [pwStrengthFeedback, setPwStrengthFeedback] = useState("");
  const pwZxcvbnRef = useRef<ZxcvbnFn | null>(null);

  // Per-row inline action state
  const [busyId, setBusyId] = useState<number | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [rowNotice, setRowNotice] = useState<string | null>(null);
  // Inline confirmation state for the "Resetear cuota" action.
  const [confirmResetId, setConfirmResetId] = useState<number | null>(null);
  // Inline confirmation state for the "Eliminar" action.
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  // Permisos tab
  const [perms, setPerms] = useState<PermissionCell[]>([]);
  const [permsDraft, setPermsDraft] = useState<Record<string, boolean>>({});
  const [permsLoading, setPermsLoading] = useState(false);
  const [permsSaving, setPermsSaving] = useState(false);
  const [permsError, setPermsError] = useState<string | null>(null);

  // Runtime-mutable app settings (admin can toggle public registration
  // without redeploying — backed by the app_settings table).
  const [appSettings, setAppSettings] = useState<AppSettingsView | null>(null);
  const [appSettingsSaving, setAppSettingsSaving] = useState(false);
  const [appSettingsError, setAppSettingsError] = useState<string | null>(null);

  useEffect(() => {
    void getAppSettings()
      .then(setAppSettings)
      .catch((err) =>
        setAppSettingsError(
          err instanceof ApiError ? err.detail : "Error cargando ajustes"
        )
      );
  }, []);

  async function togglePublicRegistration(next: boolean) {
    setAppSettingsSaving(true);
    setAppSettingsError(null);
    try {
      const updated = await setPublicRegistrationEnabled(next);
      setAppSettings(updated);
    } catch (err) {
      setAppSettingsError(
        err instanceof ApiError ? err.detail : "No se pudo actualizar"
      );
    } finally {
      setAppSettingsSaving(false);
    }
  }

  // Audit tab
  const [audit, setAudit] = useState<AuditLogEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditAction, setAuditAction] = useState<string>("");
  const [auditActor, setAuditActor] = useState("");
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditHasMore, setAuditHasMore] = useState(false);

  // Create user modal
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: "",
    email: "",
    password: "",
    role: "analyst" as UserRole,
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    void loadUsers();
  }, []);

  // Lazy-load zxcvbn when the reset-password modal opens.
  useEffect(() => {
    if (!pwUser || pwZxcvbnRef.current) return;
    loadZxcvbn().then((fn) => {
      pwZxcvbnRef.current = fn;
      if (newPassword) {
        const r = fn(newPassword);
        setPwStrengthScore(r.score);
        setPwStrengthFeedback(r.feedback.warning || r.feedback.suggestions[0] || "");
      }
    });
  }, [pwUser, newPassword]);

  // Re-score password on every change while the modal is open.
  useEffect(() => {
    if (!pwUser || !pwZxcvbnRef.current) return;
    if (!newPassword) {
      setPwStrengthScore(0);
      setPwStrengthFeedback("");
      return;
    }
    const r = pwZxcvbnRef.current(newPassword);
    setPwStrengthScore(r.score);
    setPwStrengthFeedback(r.feedback.warning || r.feedback.suggestions[0] || "");
  }, [newPassword, pwUser]);

  const pwEval = useMemo(() => evaluatePassword(newPassword), [newPassword]);
  const pwMatch =
    newPassword.length > 0 && newPassword === newPasswordConfirm;
  const pwCanSubmit =
    pwEval.allRulesPass &&
    pwStrengthScore >= MIN_STRENGTH_SCORE &&
    pwMatch;

  const loadAudit = async (offset = 0) => {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const data = await getAuditLog({
        limit: AUDIT_PAGE_SIZE,
        offset,
        action: auditAction || undefined,
        actor_email: auditActor.trim() || undefined,
      });
      setAudit(data);
      setAuditOffset(offset);
      setAuditHasMore(data.length === AUDIT_PAGE_SIZE);
    } catch (err) {
      setAuditError(
        err instanceof ApiError ? err.detail : "Error cargando auditoría"
      );
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    if (tab === "auditoria") void loadAudit(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, auditAction]);

  const cellKey = (role: UserRole, k: string) => `${role}::${k}`;

  const loadPerms = async () => {
    setPermsLoading(true);
    setPermsError(null);
    try {
      const data = await getPermissions();
      setPerms(data);
      const draft: Record<string, boolean> = {};
      data.forEach((c) => {
        draft[cellKey(c.role, c.permission_key)] = c.allowed;
      });
      setPermsDraft(draft);
    } catch (err) {
      setPermsError(err instanceof ApiError ? err.detail : "Error cargando permisos");
    } finally {
      setPermsLoading(false);
    }
  };

  useEffect(() => {
    if (tab === "permisos") void loadPerms();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  async function savePermissions() {
    const changes: PermissionChange[] = perms
      .filter((c) => !c.locked && permsDraft[cellKey(c.role, c.permission_key)] !== c.allowed)
      .map((c) => ({
        role: c.role,
        permission_key: c.permission_key,
        allowed: permsDraft[cellKey(c.role, c.permission_key)],
      }));

    if (changes.length === 0) return;

    setPermsSaving(true);
    setPermsError(null);
    try {
      const updated = await updatePermissions(changes);
      setPerms(updated);
      const draft: Record<string, boolean> = {};
      updated.forEach((c) => {
        draft[cellKey(c.role, c.permission_key)] = c.allowed;
      });
      setPermsDraft(draft);
    } catch (err) {
      setPermsError(err instanceof ApiError ? err.detail : "No se pudieron guardar los cambios");
    } finally {
      setPermsSaving(false);
    }
  }

  function resetPermsDraft() {
    const draft: Record<string, boolean> = {};
    perms.forEach((c) => {
      draft[cellKey(c.role, c.permission_key)] = c.allowed;
    });
    setPermsDraft(draft);
  }

  async function loadUsers() {
    setLoading(true);
    setError(null);
    try {
      const data = await getAdminUsers();
      setUsers(data);
    } catch {
      setError("Error cargando usuarios");
    } finally {
      setLoading(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    if (!pwUser) return;
    if (!pwCanSubmit) {
      setPwError(
        "La contraseña no cumple la política de seguridad (revisa los requisitos).",
      );
      return;
    }
    setPwLoading(true);
    setPwError(null);
    try {
      await adminChangePassword(pwUser.id, newPassword);
      setPwUser(null);
      setNewPassword("");
      setNewPasswordConfirm("");
      setPwStrengthScore(0);
      setPwStrengthFeedback("");
    } catch (err) {
      setPwError(err instanceof ApiError ? err.detail : "Error al actualizar la contraseña");
    } finally {
      setPwLoading(false);
    }
  }

  async function handleRoleChange(target: AdminUserView, role: UserRole) {
    if (target.role === role) return;
    setBusyId(target.id);
    setRowError(null);
    try {
      await adminChangeRole(target.id, role);
      // Refetch so quota fields stay in sync (adminChangeRole returns UserMe).
      await loadUsers();
    } catch (err) {
      setRowError(
        err instanceof ApiError ? err.detail : "No se pudo cambiar el rol"
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleLevelChange(target: AdminUserView, level: UserLevel) {
    // Even if the chosen level equals the current one, hit the endpoint
    // so a pending account gets approved with a single click ("confirm
    // L1" is a valid action).
    setBusyId(target.id);
    setRowError(null);
    setRowNotice(null);
    try {
      await adminChangeLevel(target.id, level);
      setRowNotice(
        target.level_approved
          ? `Nivel de ${target.email} actualizado a ${level}.`
          : `Cuenta de ${target.email} aprobada con nivel ${level}.`,
      );
      await loadUsers();
    } catch (err) {
      setRowError(
        err instanceof ApiError ? err.detail : "No se pudo asignar el nivel",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault();
    setCreateLoading(true);
    setCreateError(null);
    try {
      await adminCreateUser(createForm);
      await loadUsers();
      setCreateOpen(false);
      setCreateForm({ name: "", email: "", password: "", role: "analyst" });
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? err.detail : "No se pudo crear el usuario"
      );
    } finally {
      setCreateLoading(false);
    }
  }

  async function handleResetQuota(target: AdminUserView) {
    setBusyId(target.id);
    setRowError(null);
    setRowNotice(null);
    try {
      const result = await adminResetLlmQuota(target.id);
      setRowNotice(
        `Cuota reseteada para ${target.email} (previo: ${result.previous_count}).`,
      );
      await loadUsers();
    } catch (err) {
      setRowError(
        err instanceof ApiError ? err.detail : "No se pudo resetear la cuota",
      );
    } finally {
      setConfirmResetId(null);
      setBusyId(null);
    }
  }

  async function handleResetMfa(target: AdminUserView) {
    if (
      !window.confirm(
        `¿Resetear el MFA de ${target.email}? Se cerrarán sus sesiones y deberá volver a escanear el QR.`,
      )
    )
      return;
    setBusyId(target.id);
    setRowError(null);
    setRowNotice(null);
    try {
      await adminResetMfa(target.id);
      setRowNotice(`MFA reseteado para ${target.email}.`);
      await loadUsers();
    } catch (err) {
      setRowError(err instanceof ApiError ? err.detail : "No se pudo resetear el MFA");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(target: AdminUserView) {
    setBusyId(target.id);
    setRowError(null);
    try {
      await adminDeleteUser(target.id);
      setUsers((prev) => prev.filter((u) => u.id !== target.id));
    } catch (err) {
      setRowError(
        err instanceof ApiError ? err.detail : "No se pudo eliminar el usuario"
      );
    } finally {
      setConfirmDeleteId(null);
      setBusyId(null);
    }
  }

  const meId = auth.user?.id ?? -1;

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-rose-300/80 mb-1">
            Zona de administración
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
            Administración
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Gestión de usuarios, roles y permisos del sistema.
          </p>
        </div>
        <div className="text-xs font-mono text-slate-500 text-right">
          {users.length} cuentas
        </div>
      </header>

      <nav className="inline-flex gap-1 p-1 rounded-lg border border-ink-700 bg-ink-900/60">
        {(["usuarios", "roles", "permisos", "auditoria"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={
              "px-4 py-1.5 text-xs capitalize rounded-md transition " +
              (tab === t
                ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30"
                : "text-slate-400 hover:text-slate-200 border border-transparent")
            }
          >
            {t}
          </button>
        ))}
      </nav>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 p-4 rounded">
          {error}
        </div>
      )}

      {tab === "usuarios" && (
        <>
          {/* Registro público: toggle global. Vive en app_settings (DB)
              y manda sobre ALLOW_PUBLIC_REGISTRATION del .env, así que el
              cambio surte efecto sin reiniciar la API. */}
          <section className="bg-ink-900/60 border border-ink-700 rounded-xl p-4 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-slate-100">
                Registro público
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                {appSettings === null
                  ? "Cargando estado..."
                  : appSettings.public_registration_enabled
                  ? "Abierto: cualquier persona con el enlace puede crear una cuenta. Recuerda cerrarlo cuando termines la prueba."
                  : "Cerrado: solo se pueden crear cuentas desde aquí (botón \"+ Crear usuario\")."}
              </p>
              {appSettingsError && (
                <p className="text-xs text-rose-300 mt-1">{appSettingsError}</p>
              )}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span
                className={`text-xs px-2 py-1 rounded-full border ${
                  appSettings?.public_registration_enabled
                    ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                    : "bg-slate-500/10 text-slate-300 border-slate-500/30"
                }`}
              >
                {appSettings?.public_registration_enabled ? "Abierto" : "Cerrado"}
              </span>
              <button
                type="button"
                disabled={appSettings === null || appSettingsSaving}
                onClick={() =>
                  appSettings &&
                  void togglePublicRegistration(
                    !appSettings.public_registration_enabled,
                  )
                }
                className={`px-3 py-1.5 text-sm rounded-md font-medium disabled:opacity-50 ${
                  appSettings?.public_registration_enabled
                    ? "bg-rose-500 hover:bg-rose-400 text-ink-950"
                    : "bg-cyan-500 hover:bg-cyan-400 text-ink-950"
                }`}
              >
                {appSettingsSaving
                  ? "Aplicando..."
                  : appSettings?.public_registration_enabled
                  ? "Cerrar registro"
                  : "Abrir registro"}
              </button>
            </div>
          </section>

        <section className="bg-ink-900/60 border border-ink-700 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-ink-700 bg-ink-900/60 flex justify-between items-center">
            <div className="flex items-baseline gap-3">
              <h2 className="text-xl font-semibold">Usuarios Registrados</h2>
              <span className="text-xs text-slate-500">{users.length} cuentas</span>
            </div>
            <button
              onClick={() => {
                setCreateOpen(true);
                setCreateError(null);
              }}
              className="px-3 py-1.5 text-sm bg-cyan-500 text-ink-950 hover:bg-cyan-400 rounded-md font-medium"
            >
              + Crear usuario
            </button>
          </div>

          {rowError && (
            <div className="px-4 py-2 bg-rose-500/10 border-b border-rose-500/30 text-rose-300 text-sm">
              {rowError}
            </div>
          )}

          {rowNotice && (
            <div className="px-4 py-2 bg-emerald-500/10 border-b border-emerald-500/30 text-emerald-300 text-sm flex justify-between items-center">
              <span>{rowNotice}</span>
              <button
                onClick={() => setRowNotice(null)}
                className="text-xs text-emerald-300 hover:text-emerald-200"
              >
                cerrar
              </button>
            </div>
          )}

          {loading ? (
            <div className="p-8 text-center text-slate-400">Cargando usuarios...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm whitespace-nowrap">
                <thead className="bg-ink-850 text-slate-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">ID</th>
                    <th className="px-4 py-3 font-medium">Nombre</th>
                    <th className="px-4 py-3 font-medium">Email</th>
                    <th className="px-4 py-3 font-medium">Rol</th>
                    <th className="px-4 py-3 font-medium">Nivel SOC</th>
                    <th className="px-4 py-3 font-medium">Cuota hoy</th>
                    <th className="px-4 py-3 font-medium text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700/60">
                  {users.map((u) => {
                    const isSelf = u.id === meId;
                    const busy = busyId === u.id;
                    const used = u.server_llm_calls_today;
                    const limit = u.server_llm_quota_limit;
                    const ratio = limit > 0 ? used / limit : 0;
                    let quotaTone = "bg-ink-800/40 text-slate-300 border-ink-700";
                    if (!u.byo_key_configured) {
                      if (used >= limit) {
                        quotaTone =
                          "bg-rose-500/15 text-rose-300 border-rose-500/30";
                      } else if (ratio >= 0.8) {
                        quotaTone =
                          "bg-amber-500/15 text-amber-300 border-amber-500/30";
                      }
                    }
                    const confirmingReset = confirmResetId === u.id;
                    const confirmingDelete = confirmDeleteId === u.id;
                    return (
                      <tr key={u.id} className="hover:bg-ink-800/40">
                        <td className="px-4 py-3 text-slate-400">{u.id}</td>
                        <td className="px-4 py-3 font-medium text-slate-200">
                          {u.name}
                          {isSelf && (
                            <span className="ml-2 text-xs text-cyan-400">(tú)</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-400">{u.email}</td>
                        <td className="px-4 py-3">
                          <select
                            value={u.role}
                            disabled={busy || isSelf}
                            onChange={(e) =>
                              handleRoleChange(u, e.target.value as UserRole)
                            }
                            className="bg-ink-950 border border-ink-700 rounded px-2 py-1 text-xs disabled:opacity-50"
                          >
                            <option value="analyst">analyst</option>
                            <option value="admin">admin</option>
                          </select>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <select
                              value={u.level}
                              disabled={busy}
                              onChange={(e) =>
                                handleLevelChange(u, e.target.value as UserLevel)
                              }
                              className="bg-ink-950 border border-ink-700 rounded px-2 py-1 text-xs disabled:opacity-50"
                              title={
                                u.level_approved
                                  ? `Solicitó ${u.requested_level} en registro`
                                  : `Pendiente — solicitó ${u.requested_level}`
                              }
                            >
                              <option value="L1">L1</option>
                              <option value="L2">L2</option>
                              <option value="INSTRUCTOR">INSTRUCTOR</option>
                            </select>
                            {!u.level_approved ? (
                              <span
                                className="px-1.5 py-0.5 rounded border text-[10px] font-medium uppercase bg-amber-500/10 text-amber-300 border-amber-500/30"
                                title={`Pendiente de aprobación — solicitó ${u.requested_level}`}
                              >
                                pend · {u.requested_level}
                              </span>
                            ) : u.requested_level !== u.level ? (
                              <span
                                className="text-[10px] text-slate-500"
                                title={`Solicitó ${u.requested_level}, asignado ${u.level}`}
                              >
                                (pidió {u.requested_level})
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {u.byo_key_configured ? (
                            <span
                              className="px-2 py-0.5 rounded border text-xs bg-cyan-500/10 text-cyan-300 border-cyan-500/30"
                              title="Usuario con BYO key — no consume cuota del servidor"
                            >
                              BYO
                            </span>
                          ) : (
                            <span
                              className={`px-2 py-0.5 rounded border text-xs font-mono ${quotaTone}`}
                            >
                              {used}/{limit}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap justify-end gap-2">
                            {confirmingReset ? (
                              <>
                                <span className="self-center text-xs text-amber-300">
                                  ¿Resetear?
                                </span>
                                <button
                                  disabled={busy}
                                  onClick={() => handleResetQuota(u)}
                                  className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  Sí
                                </button>
                                <button
                                  disabled={busy}
                                  onClick={() => setConfirmResetId(null)}
                                  className="rounded border border-ink-700 bg-ink-800/40 px-2.5 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-ink-800/70 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  No
                                </button>
                              </>
                            ) : (
                              <button
                                disabled={
                                  busy || u.byo_key_configured || used === 0
                                }
                                onClick={() => {
                                  setRowNotice(null);
                                  setRowError(null);
                                  setConfirmResetId(u.id);
                                }}
                                className="rounded border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-300 transition-colors hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                                title={
                                  u.byo_key_configured
                                    ? "El usuario tiene BYO key — la cuota del servidor no aplica"
                                    : used === 0
                                      ? "Sin consumo hoy — nada que resetear"
                                      : "Pone el contador del día a 0"
                                }
                              >
                                Resetear cuota
                              </button>
                            )}
                            <button
                              disabled={busy || !u.mfa_enabled}
                              onClick={() => void handleResetMfa(u)}
                              className="rounded border border-violet-500/40 bg-violet-500/10 px-2.5 py-1 text-xs font-medium text-violet-300 transition-colors hover:bg-violet-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                              title={
                                u.mfa_enabled
                                  ? "Borra el segundo factor (móvil perdido). Cierra sus sesiones; deberá enrolarse de nuevo."
                                  : "MFA aún no activado por el usuario"
                              }
                            >
                              {u.mfa_enabled ? "Reset MFA" : "MFA pendiente"}
                            </button>
                            <button
                              disabled={busy}
                              onClick={() => {
                                setPwUser(u);
                                setNewPassword("");
                                setNewPasswordConfirm("");
                                setPwStrengthScore(0);
                                setPwStrengthFeedback("");
                                setPwError(null);
                              }}
                              className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1 text-xs font-medium text-cyan-300 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              Resetear contraseña
                            </button>
                            {confirmingDelete ? (
                              <>
                                <span className="self-center text-xs text-rose-300">
                                  ¿Eliminar?
                                </span>
                                <button
                                  disabled={busy}
                                  onClick={() => handleDelete(u)}
                                  className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  Sí
                                </button>
                                <button
                                  disabled={busy}
                                  onClick={() => setConfirmDeleteId(null)}
                                  className="rounded border border-ink-700 bg-ink-800/40 px-2.5 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-ink-800/70 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  No
                                </button>
                              </>
                            ) : (
                              <button
                                disabled={busy || isSelf}
                                onClick={() => {
                                  setRowNotice(null);
                                  setRowError(null);
                                  setConfirmDeleteId(u.id);
                                }}
                                className="rounded border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                                title={
                                  isSelf
                                    ? "No puedes eliminar tu propia cuenta"
                                    : "Eliminar usuario — acción no reversible"
                                }
                              >
                                Eliminar
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
        </>
      )}

      {tab === "roles" && (
        <section className="grid gap-4 md:grid-cols-2">
          {(Object.entries(ROLE_DESCRIPTIONS) as [UserRole, typeof ROLE_DESCRIPTIONS["admin"]][]).map(
            ([role, info]) => {
              const count = users.filter((u) => u.role === role).length;
              return (
                <article
                  key={role}
                  className="bg-ink-900/60 border border-ink-700 rounded-xl p-5 space-y-3"
                >
                  <header className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold">{info.title}</h3>
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        role === "admin"
                          ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                          : "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"
                      }`}
                    >
                      {role}
                    </span>
                  </header>
                  <p className="text-sm text-slate-400">{info.blurb}</p>
                  <p className="text-xs text-slate-500">
                    Usuarios con este rol: <span className="text-slate-300">{count}</span>
                  </p>
                </article>
              );
            }
          )}
          <p className="md:col-span-2 text-xs text-slate-500">
            Los roles están definidos en <code>app/models.py::UserRole</code> y se
            asignan en el alta o desde la pestaña Usuarios. El primer registro pasa
            automáticamente a admin.
          </p>
        </section>
      )}

      {tab === "permisos" && (
        <section className="bg-ink-900/60 border border-ink-700 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-ink-700 bg-ink-900/60 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">Matriz de Permisos</h2>
              <p className="text-xs text-slate-500 mt-1">
                Activa o desactiva cada acción por rol. Las filas marcadas como
                <span className="mx-1 px-1 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30">locked</span>
                no se pueden modificar (protección anti-lockout). Las baseline
                (alertas, chat, logs) están abiertas a cualquier usuario autenticado
                y se aplican en código.
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={resetPermsDraft}
                disabled={permsSaving || permsLoading}
                className="px-3 py-1.5 text-sm bg-ink-900 border border-ink-700 hover:border-cyan-500/40 disabled:opacity-50 rounded-md"
              >
                Descartar
              </button>
              <button
                onClick={() => void savePermissions()}
                disabled={permsSaving || permsLoading}
                className="px-3 py-1.5 text-sm bg-cyan-500 text-ink-950 hover:bg-cyan-400 disabled:bg-ink-800 disabled:text-slate-500 rounded-md font-medium"
              >
                {permsSaving ? "Guardando..." : "Guardar cambios"}
              </button>
            </div>
          </div>

          {permsError && (
            <div className="px-4 py-2 bg-rose-500/10 border-b border-rose-500/30 text-rose-300 text-sm">
              {permsError}
            </div>
          )}

          {permsLoading ? (
            <div className="p-8 text-center text-slate-400">Cargando matriz...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-ink-850 text-slate-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Área</th>
                    <th className="px-4 py-3 font-medium">Acción</th>
                    <th className="px-4 py-3 font-medium text-center">Analyst</th>
                    <th className="px-4 py-3 font-medium text-center">Admin</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700/60">
                  {/* Baseline (informativo) */}
                  {BASELINE_CAPS.map((cap, i) => (
                    <tr key={`base-${i}`} className="hover:bg-ink-800/40 opacity-70">
                      <td className="px-4 py-3 text-slate-400">{cap.area}</td>
                      <td className="px-4 py-3 text-slate-200">
                        {cap.action}
                        <span className="ml-2 text-[10px] text-slate-500">(baseline)</span>
                      </td>
                      <td className="px-4 py-3 text-center text-emerald-300">✓</td>
                      <td className="px-4 py-3 text-center text-emerald-300">✓</td>
                    </tr>
                  ))}

                  {/* Configurables (de la registry del backend) */}
                  {Array.from(
                    new Set(perms.map((c) => c.permission_key))
                  ).map((key) => {
                    const analyst = perms.find(
                      (c) => c.permission_key === key && c.role === "analyst"
                    );
                    const admin = perms.find(
                      (c) => c.permission_key === key && c.role === "admin"
                    );
                    if (!analyst || !admin) return null;
                    return (
                      <tr key={key} className="hover:bg-ink-800/40">
                        <td className="px-4 py-3 text-slate-400">{analyst.area}</td>
                        <td className="px-4 py-3 text-slate-200">
                          {analyst.action}
                          <code className="ml-2 text-[10px] text-slate-600">{key}</code>
                          {analyst.locked && (
                            <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-300 border border-amber-500/30">
                              locked
                            </span>
                          )}
                        </td>
                        {[analyst, admin].map((cell) => (
                          <td key={cell.role} className="px-4 py-3 text-center">
                            <input
                              type="checkbox"
                              disabled={cell.locked}
                              checked={
                                permsDraft[cellKey(cell.role, cell.permission_key)] ?? cell.allowed
                              }
                              onChange={(e) =>
                                setPermsDraft((prev) => ({
                                  ...prev,
                                  [cellKey(cell.role, cell.permission_key)]: e.target.checked,
                                }))
                              }
                              className="rounded bg-ink-950 border-ink-700 disabled:opacity-40"
                            />
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "auditoria" && (
        <section className="bg-ink-900/60 border border-ink-700 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-ink-700 bg-ink-900/60 flex flex-wrap gap-3 items-end justify-between">
            <div>
              <h2 className="text-xl font-semibold">Registro de Auditoría</h2>
              <p className="text-xs text-slate-500 mt-1">
                Acciones administrativas registradas en orden cronológico inverso.
                Solo lectura.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="block text-xs">
                <span className="text-slate-400 block mb-1">Acción</span>
                <select
                  value={auditAction}
                  onChange={(e) => setAuditAction(e.target.value)}
                  className="bg-ink-950 border border-ink-700 rounded px-2 py-1 text-slate-200 text-sm"
                >
                  {ACTION_OPTIONS.map((a) => (
                    <option key={a} value={a}>
                      {a === "" ? "(todas)" : a}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs">
                <span className="text-slate-400 block mb-1">Actor (email)</span>
                <input
                  type="text"
                  value={auditActor}
                  onChange={(e) => setAuditActor(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadAudit(0);
                  }}
                  placeholder="substring"
                  className="bg-ink-950 border border-ink-700 rounded px-2 py-1 text-slate-200 text-sm"
                />
              </label>
              <button
                onClick={() => void loadAudit(0)}
                className="px-3 py-1.5 text-sm bg-cyan-500 text-ink-950 hover:bg-cyan-400 rounded-md font-medium"
              >
                Aplicar
              </button>
            </div>
          </div>

          {auditError && (
            <div className="px-4 py-2 bg-rose-500/10 border-b border-rose-500/30 text-rose-300 text-sm">
              {auditError}
            </div>
          )}

          {auditLoading ? (
            <div className="p-8 text-center text-slate-400">Cargando registros...</div>
          ) : audit.length === 0 ? (
            <div className="p-8 text-center text-slate-500">
              No hay registros para los filtros actuales.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-ink-850 text-slate-400">
                  <tr>
                    <th className="px-3 py-2 font-medium whitespace-nowrap">Fecha</th>
                    <th className="px-3 py-2 font-medium">Actor</th>
                    <th className="px-3 py-2 font-medium">Acción</th>
                    <th className="px-3 py-2 font-medium">Objetivo</th>
                    <th className="px-3 py-2 font-medium">Detalles</th>
                    <th className="px-3 py-2 font-medium">IP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700/60 font-mono">
                  {audit.map((e) => (
                    <tr key={e.id} className="hover:bg-ink-800/40 align-top">
                      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                        {new Date(e.created_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-slate-200">
                        {e.actor_email}
                        <span className="text-slate-500"> #{e.actor_id ?? "—"}</span>
                      </td>
                      <td className="px-3 py-2">
                        <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                          {e.action}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-300">
                        {e.target_label ? (
                          <>
                            {e.target_label}
                            <span className="text-slate-500"> #{e.target_id}</span>
                          </>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-400 max-w-md break-all">
                        {e.details ? (
                          <code className="text-[11px]">{JSON.stringify(e.details)}</code>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-500">
                        {e.ip ?? <span className="text-slate-700">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="p-3 border-t border-ink-700 bg-ink-850 flex justify-between items-center text-sm">
            <button
              onClick={() => void loadAudit(Math.max(0, auditOffset - AUDIT_PAGE_SIZE))}
              disabled={auditOffset === 0 || auditLoading}
              className="px-3 py-1 bg-ink-900 border border-ink-700 hover:border-cyan-500/40 disabled:opacity-50 rounded-md"
            >
              Anterior
            </button>
            <span className="text-slate-400">
              Mostrando {audit.length} registros desde offset {auditOffset}
            </span>
            <button
              onClick={() => void loadAudit(auditOffset + AUDIT_PAGE_SIZE)}
              disabled={!auditHasMore || auditLoading}
              className="px-3 py-1 bg-ink-900 border border-ink-700 hover:border-cyan-500/40 disabled:opacity-50 rounded-md"
            >
              Siguiente
            </button>
          </div>
        </section>
      )}

      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <form
            onSubmit={handleCreateUser}
            className="w-full max-w-sm bg-ink-900 border border-ink-700 rounded-xl shadow-xl p-6 space-y-4"
          >
            <h3 className="text-lg font-bold">{t("tile_admin_title")} — {t("login_name")}</h3>

            {createError && (
              <div className="text-xs bg-rose-500/10 text-rose-300 p-2 rounded border border-rose-500/30">
                {createError}
              </div>
            )}

            <label className="block text-sm">
              <span className="text-slate-400">Nombre</span>
              <input
                type="text"
                required
                minLength={2}
                maxLength={100}
                value={createForm.name}
                onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                className="mt-1 w-full rounded-md bg-ink-950 border border-ink-700 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="block text-sm">
              <span className="text-slate-400">Email</span>
              <input
                type="email"
                required
                value={createForm.email}
                onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                className="mt-1 w-full rounded-md bg-ink-950 border border-ink-700 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="block text-sm">
              <span className="text-slate-400">Contraseña</span>
              <input
                type="password"
                required
                minLength={10}
                autoComplete="new-password"
                value={createForm.password}
                onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                className="mt-1 w-full rounded-md bg-ink-950 border border-ink-700 px-3 py-2 text-slate-100"
                placeholder="Mín. 10 chars · mayús/minús/dígito/símbolo"
              />
            </label>

            <label className="block text-sm">
              <span className="text-slate-400">Rol</span>
              <select
                value={createForm.role}
                onChange={(e) =>
                  setCreateForm({ ...createForm, role: e.target.value as UserRole })
                }
                className="mt-1 w-full rounded-md bg-ink-950 border border-ink-700 px-3 py-2 text-slate-100"
              >
                <option value="analyst">analyst</option>
                <option value="admin">admin</option>
              </select>
            </label>

            <div className="flex justify-end gap-3 mt-6">
              <button
                type="button"
                onClick={() => {
                  setCreateOpen(false);
                  setCreateError(null);
                }}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={createLoading}
                className="px-4 py-2 text-sm bg-cyan-500 text-ink-950 hover:bg-cyan-400 disabled:bg-ink-800 disabled:text-slate-500 rounded-md font-medium"
              >
                {createLoading ? "…" : t("login_register_btn")}
              </button>
            </div>
          </form>
        </div>
      )}

      {pwUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <form
            onSubmit={handleChangePassword}
            className="w-full max-w-sm bg-ink-900 border border-ink-700 rounded-xl shadow-xl p-6 space-y-4"
          >
            <h3 className="text-lg font-bold">Resetear contraseña</h3>
            <p className="text-sm text-slate-400">
              Usuario: <span className="text-slate-200">{pwUser.email}</span>
            </p>
            <p className="text-xs text-amber-400">
              Tras el cambio, las sesiones activas del usuario quedan invalidadas.
            </p>

            {pwError && (
              <div className="text-xs bg-rose-500/10 text-rose-300 p-2 rounded border border-rose-500/30">
                {pwError}
              </div>
            )}

            <label className="block text-sm">
              <span className="text-slate-400">Nueva contraseña</span>
              <input
                type="password"
                required
                minLength={10}
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="mt-1 w-full rounded-md bg-ink-950 border border-ink-700 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="block text-sm">
              <span className="text-slate-400">Confirmar contraseña</span>
              <input
                type="password"
                required
                minLength={10}
                autoComplete="new-password"
                value={newPasswordConfirm}
                onChange={(e) => setNewPasswordConfirm(e.target.value)}
                className="mt-1 w-full rounded-md bg-ink-950 border border-ink-700 px-3 py-2 text-slate-100"
              />
              {newPasswordConfirm && (
                <span
                  className={`mt-1 block text-[11px] ${
                    pwMatch ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {pwMatch
                    ? "✓ Las contraseñas coinciden"
                    : "✕ Las contraseñas no coinciden"}
                </span>
              )}
            </label>

            {newPassword && (
              <div className="space-y-2">
                <div className="flex gap-1">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <div
                      key={i}
                      className={`h-1.5 flex-1 rounded ${
                        i <= pwStrengthScore
                          ? STRENGTH_COLORS[pwStrengthScore]
                          : "bg-slate-800"
                      }`}
                    />
                  ))}
                </div>
                <p className="text-[11px] text-slate-400">
                  Fortaleza:{" "}
                  <span className="font-medium text-slate-200">
                    {STRENGTH_LABELS[pwStrengthScore]}
                  </span>
                  {pwStrengthFeedback ? ` — ${pwStrengthFeedback}` : ""}
                </p>
                <ul className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
                  {pwEval.rules.map((r) => (
                    <li
                      key={r.id}
                      className={r.ok ? "text-emerald-400" : "text-slate-500"}
                    >
                      {r.ok ? "✓" : "○"} {r.label}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end gap-3 mt-6">
              <button
                type="button"
                onClick={() => {
                  setPwUser(null);
                  setNewPassword("");
                  setNewPasswordConfirm("");
                  setPwError(null);
                  setPwStrengthScore(0);
                  setPwStrengthFeedback("");
                }}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={pwLoading || !pwCanSubmit}
                className="px-4 py-2 text-sm bg-cyan-500 text-ink-950 hover:bg-cyan-400 disabled:bg-ink-800 disabled:text-slate-500 disabled:cursor-not-allowed rounded-md font-medium"
              >
                {pwLoading ? "…" : t("profile_save")}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
