export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

const DEFAULT_TIMEOUT_MS = 60_000;

// ─── Types ────────────────────────────────────────────────────────────────

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface ExplainRequest {
  log: string;
  source?: string;
  model?: string;
}

export interface ExplainResponse {
  id: number | null;
  summary: string;
  risk_level: RiskLevel;
  mitre_techniques: string[];
  reasoning: string;
}

export interface RecommendAction {
  title: string;
  detail: string;
  rationale: string;
}

export interface RecommendRequest {
  alert_id?: number;
  log?: string;
  source?: string;
  model?: string;
}

export interface RecommendResponse {
  id: number | null;
  alert_id: number | null;
  actions: RecommendAction[];
  priority: RiskLevel;
  learning_notes: string;
}

export interface AlertSummary {
  id: number;
  source: string | null;
  summary: string | null;
  risk_level: RiskLevel | null;
  mitre_techniques: string[] | null;
  created_at: string;
  // SIEM ingestion (Práctica 2)
  origin: AlertOrigin;
  external_id: string | null;
  rule_level: number | null;
  agent_name: string | null;
  event_at: string | null;
  analyzed_at: string | null;
}

export type AlertOrigin = "manual" | "wazuh";

export interface RecommendationDetail {
  id: number;
  actions: RecommendAction[];
  priority: RiskLevel;
  learning_notes: string | null;
  created_at: string;
}

export interface AlertDetail extends AlertSummary {
  log: string;
  reasoning: string | null;
  recommendations: RecommendationDetail[];
}

// ─── Internal fetch helper ────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
  }
}

// UI language chosen in the top bar (persisted by I18nProvider). Sent as
// Accept-Language so the backend answers in the same language
// (Práctica 2 · ES/EN). Falls back to the browser's own header.
function uiLanguage(): string | undefined {
  try {
    return localStorage.getItem("soc:locale") ?? undefined;
  } catch {
    return undefined;
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = init;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(uiLanguage() ? { "Accept-Language": uiLanguage() as string } : {}),
        ...(rest.headers ?? {}),
      },
      signal: ctrl.signal,
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new ApiError(res.status, detail);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Timeout tras ${timeoutMs / 1000}s — reintenta`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Public API ───────────────────────────────────────────────────────────

export const explainAlert = (payload: ExplainRequest) =>
  request<ExplainResponse>("/api/explain", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const recommendActions = (payload: RecommendRequest) =>
  request<RecommendResponse>("/api/recommend", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listAlerts = (
  limit = 50,
  offset = 0,
  filters: { origin?: AlertOrigin; pending?: boolean } = {},
) => {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (filters.origin) qs.set("origin", filters.origin);
  if (filters.pending != null) qs.set("pending", String(filters.pending));
  return request<AlertSummary[]>(`/api/alerts?${qs.toString()}`);
};

export const analyzeStoredAlert = (id: number, model?: string) =>
  request<AlertDetail>(`/api/alerts/${id}/analyze`, {
    method: "POST",
    body: JSON.stringify(model ? { model } : {}),
  });

// ─── Wazuh SIEM integration ───────────────────────────────────────────────

export interface WazuhStatus {
  push_enabled: boolean;
  pull_enabled: boolean;
  poll_interval_seconds: number;
  min_rule_level: number;
  indexer_url: string | null;
  push_last_received: string | null;
  pull_last_run: string | null;
  pull_last_error: string | null;
  pull_cursor: string | null;
  alerts_total: number;
  alerts_last_24h: number;
  alerts_pending: number;
}

export interface WazuhPullResult {
  fetched: number;
  received: number;
  created: number;
  duplicates: number;
  below_threshold: number;
  invalid: number;
  cursor: string;
}

export const getWazuhStatus = () =>
  request<WazuhStatus>("/api/integrations/wazuh/status");

export const wazuhPullNow = () =>
  request<WazuhPullResult>("/api/integrations/wazuh/pull", { method: "POST" });

export const getAlert = (id: number) =>
  request<AlertDetail>(`/api/alerts/${id}`);

// ─── Chat ─────────────────────────────────────────────────────────────────

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  log_context?: string;
  model?: string;
}

export interface ChatResponse {
  reply: string;
  sources: string[];
  language?: string;
}

export const sendChat = (payload: ChatRequest) =>
  request<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ─── Incident report (PDF) ───────────────────────────────────────────────

export interface IncidentReportRequest {
  alert_id?: number;
  messages?: ChatMessage[];
  log_context?: string;
  title?: string;
  analyst_notes?: string;
  include_transcript?: boolean;
  model?: string;
}

/** POST /api/reports/incident → triggers a browser download of the PDF. */
export async function downloadIncidentReport(
  payload: IncidentReportRequest,
): Promise<string> {
  const ctrl = new AbortController();
  // LLM synthesis + rendering can take a while on long conversations.
  const timer = setTimeout(() => ctrl.abort(), 120_000);
  try {
    const lang = uiLanguage();
    const res = await fetch(`${API_BASE}/api/reports/incident`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(lang ? { "Accept-Language": lang } : {}),
      },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    const blob = await res.blob();
    const disposition = res.headers.get("content-disposition") ?? "";
    const match = /filename="([^"]+)"/.exec(disposition);
    const filename = match?.[1] ?? "incident-report.pdf";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    return filename;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Timeout tras 120s — reintenta");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Stats / Dashboard ────────────────────────────────────────────────────

export interface StatsTotals {
  alerts: number;
  recommendations: number;
  users: number | null;
}

export interface RiskBucket {
  risk_level: string;
  count: number;
}

export interface MitreBucket {
  technique: string;
  count: number;
}

export interface DailyPoint {
  day: string; // YYYY-MM-DD
  count: number;
}

export interface UserBucket {
  user_id: number;
  email: string;
  alerts: number;
}

export interface StatsResponse {
  scope: "self" | "all";
  totals: StatsTotals;
  by_risk: RiskBucket[];
  top_mitre: MitreBucket[];
  daily_last_30d: DailyPoint[];
  by_user: UserBucket[] | null;
}

export const getStats = () => request<StatsResponse>("/api/stats");

// ─── Knowledge Base ───────────────────────────────────────────────────────

export interface KBStatus {
  total: number;
  mitre: number;
  owasp: number;
  unknown: number;
}

export const kbStatus = () => request<KBStatus>("/api/kb/status");

// ─── LLM ──────────────────────────────────────────────────────────────────

export interface ModelsInfo {
  default: string;
  available: string[];
}

export const getModels = () => request<ModelsInfo>("/api/llm/models");

// ─── Auth ─────────────────────────────────────────────────────────────────

export type UserRole = "analyst" | "admin";
export type UserLevel = "L1" | "L2" | "INSTRUCTOR";

export interface UserMe {
  id: number;
  name: string;
  last_name: string;
  email: string;
  role: UserRole;
  level: UserLevel;
  requested_level: UserLevel;
  level_approved: boolean;
  is_verified: boolean;
  created_at: string;
  mfa_enabled?: boolean;
}

export interface UpdateProfilePayload {
  name?: string;
  last_name?: string;
  email?: string;
  level?: UserLevel;
}

export const updateProfile = (payload: UpdateProfilePayload & { current_password?: string }) =>
  request<UserMe>("/api/auth/me", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

// ─── Per-user LLM settings (BYO Gemini key + preferred model) ─────────────

export interface LLMSettings {
  configured: boolean;
  key_last4: string | null;
  key_validated_at: string | null;
  preferred_chat_model: string | null;
  available_models: string[];
  default_model: string;
  server_quota_used: number;
  server_quota_limit: number;
}

export const getLLMSettings = () =>
  request<LLMSettings>("/api/auth/me/llm");

export const updateLLMSettings = (payload: {
  api_key?: string;
  preferred_chat_model?: string;
}) =>
  request<LLMSettings>("/api/auth/me/llm", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const clearLLMKey = () =>
  request<LLMSettings>("/api/auth/me/llm", { method: "DELETE" });

export interface LoginResponse {
  /** null while the MFA step is pending (Práctica 2 · MFA obligatorio). */
  user: UserMe | null;
  expires_at: string;
  mfa_required?: boolean;
  mfa_setup_required?: boolean;
}

// ─── MFA / TOTP ───────────────────────────────────────────────────────────

export interface MfaSetupResponse {
  secret: string;
  otpauth_uri: string;
  qr_svg_data_uri: string;
  issuer: string;
  account: string;
}

export interface MfaVerifyResponse {
  user: UserMe;
  expires_at: string;
  recovery_codes: string[] | null;
  recovery_codes_left: number;
}

export interface MfaStatus {
  required: boolean;
  enabled: boolean;
  enabled_at: string | null;
  recovery_codes_left: number;
}

export const mfaSetup = () =>
  request<MfaSetupResponse>("/api/auth/mfa/setup", { method: "POST" });

export const mfaVerify = (payload: { code?: string; recovery_code?: string }) =>
  request<MfaVerifyResponse>("/api/auth/mfa/verify", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getMfaStatus = () => request<MfaStatus>("/api/auth/mfa/status");

export const regenerateRecoveryCodes = (code: string) =>
  request<{ recovery_codes: string[] }>("/api/auth/mfa/recovery-codes", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const adminResetMfa = (userId: number) =>
  request<{ status: string; user_id: number; was_enabled: boolean }>(
    `/api/admin/users/${userId}/mfa/reset`,
    { method: "POST" },
  );

export interface RegisterResponse {
  user: UserMe;
  verification_required: boolean;
  verification_link_dev: string | null;
}

export const register = (
  email: string,
  password: string,
  name: string,
  level: UserLevel = "L1",
  website: string = "",
) =>
  request<RegisterResponse>("/api/auth/register", {
    method: "POST",
    // `website` is the honeypot. Real users leave it empty; bots fill
    // every field. Sent every time so its presence is unconditional.
    body: JSON.stringify({ email, password, name, level, website }),
  });

export const checkEmail = (email: string) =>
  request<{ available: boolean }>(
    `/api/auth/check-email?email=${encodeURIComponent(email)}`,
  );

// ─── «¿Has olvidado tu contraseña?» ──────────────────────────────────────

export const forgotPassword = (email: string) =>
  request<{ message: string; reset_link_dev: string | null }>(
    "/api/auth/forgot-password",
    { method: "POST", body: JSON.stringify({ email }) },
  );

export const resetPassword = (token: string, new_password: string) =>
  request<void>("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password }),
  });

export const verifyEmail = (token: string) =>
  request<UserMe>("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });

export interface AdminUserView {
  id: number;
  name: string;
  last_name: string;
  email: string;
  role: UserRole;
  level: UserLevel;
  requested_level: UserLevel;
  level_approved: boolean;
  created_at: string;
  server_llm_calls_today: number;
  server_llm_quota_date: string | null;
  server_llm_quota_limit: number;
  byo_key_configured: boolean;
  gemini_key_last4: string | null;
  mfa_enabled?: boolean;
}

export const getAdminUsers = () =>
  request<AdminUserView[]>("/api/admin/users");

export const adminResetLlmQuota = (userId: number) =>
  request<{ status: string; user_id: number; previous_count: number }>(
    `/api/admin/users/${userId}/reset-llm-quota`,
    { method: "POST" },
  );

export const adminCreateUser = (payload: {
  name: string;
  email: string;
  password: string;
  role: UserRole;
}) =>
  request<UserMe>("/api/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const adminChangePassword = (userId: number, new_password: string) =>
  request<void>(`/api/admin/users/${userId}/password`, {
    method: "PUT",
    body: JSON.stringify({ new_password }),
  });

export const adminChangeRole = (userId: number, role: UserRole) =>
  request<UserMe>(`/api/admin/users/${userId}/role`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  });

export const adminChangeLevel = (userId: number, level: UserLevel) =>
  request<AdminUserView>(`/api/admin/users/${userId}/level`, {
    method: "PUT",
    body: JSON.stringify({ level }),
  });

export const adminDeleteUser = (userId: number) =>
  request<void>(`/api/admin/users/${userId}`, { method: "DELETE" });

export interface AuditLogEntry {
  id: number;
  created_at: string;
  actor_id: number | null;
  actor_email: string;
  action: string;
  target_type: string | null;
  target_id: number | null;
  target_label: string | null;
  details: Record<string, unknown> | null;
  ip: string | null;
}

export interface PermissionCell {
  permission_key: string;
  area: string;
  action: string;
  role: UserRole;
  allowed: boolean;
  locked: boolean;
  default: boolean;
}

export interface PermissionChange {
  role: UserRole;
  permission_key: string;
  allowed: boolean;
}

export const getPermissions = () =>
  request<PermissionCell[]>("/api/admin/permissions");

export const updatePermissions = (changes: PermissionChange[]) =>
  request<PermissionCell[]>("/api/admin/permissions", {
    method: "PUT",
    body: JSON.stringify({ changes }),
  });

export interface AppSettingsView {
  public_registration_enabled: boolean;
}

export const getAppSettings = () =>
  request<AppSettingsView>("/api/admin/settings");

export const setPublicRegistrationEnabled = (enabled: boolean) =>
  request<AppSettingsView>("/api/admin/settings/public-registration", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

export const getAuditLog = (params: {
  limit?: number;
  offset?: number;
  action?: string;
  actor_email?: string;
} = {}) => {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.action) qs.set("action", params.action);
  if (params.actor_email) qs.set("actor_email", params.actor_email);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<AuditLogEntry[]>(`/api/admin/audit${suffix}`);
};

export const login = (email: string, password: string) =>
  request<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const logout = () =>
  request<void>("/api/auth/logout", { method: "POST" });

export const getMe = () => request<UserMe>("/api/auth/me");
