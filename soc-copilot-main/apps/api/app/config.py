from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Defaults that MUST never reach a non-development environment. If any of
# them survive into prod the service refuses to start.
_INSECURE_JWT_SECRETS = {
    "",
    "dev-only-change-me-32+chars-please",
    "change_me",
}
_INSECURE_PG_PASSWORDS = {
    "",
    "change_me",
    "change_me_in_prod",
    "postgres",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment marker. When "production" we enforce strict secrets and
    # disable developer affordances (Swagger UI, permissive cookies).
    app_env: str = "development"

    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-001"

    # Allowlist of chat models the frontend can switch to. Each must support
    # response_mime_type=application/json + response_schema (JSON mode) so
    # /api/explain and /api/recommend keep parsing structured output.
    # Comma-separated in env.
    gemini_chat_models_allowlist: str = (
        "gemini-2.5-flash-lite,gemini-2.5-flash,gemini-2.0-flash-lite"
    )

    @property
    def chat_models_list(self) -> list[str]:
        return [
            m.strip()
            for m in self.gemini_chat_models_allowlist.split(",")
            if m.strip()
        ]

    postgres_user: str = "soc"
    postgres_password: str = "change_me"
    postgres_db: str = "soc_copilot"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    chroma_host: str = "chroma"
    chroma_port: int = 8000

    api_cors_origins: str = "http://localhost:13500"

    rate_limit_enabled: bool = True
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60

    # ── Auth ────────────────────────────────────────────────────────────
    # Generate with: openssl rand -base64 48
    jwt_secret: str = "dev-only-change-me-32+chars-please"
    jwt_alg: str = "HS256"
    jwt_ttl_seconds: int = 3600  # 1h sessions
    cookie_name: str = "soc_session"
    cookie_secure: bool = False  # flip to true behind HTTPS / Caddy
    cookie_samesite: str = "lax"  # forced to "strict" in production

    # Public registration. First user becomes admin; flip to false after
    # bootstrap and create new users via admin endpoints.
    allow_public_registration: bool = True

    # ── Email verification ──────────────────────────────────────────────
    # When True, /auth/login rejects users that haven't clicked their
    # verification link. Requires SMTP_* configured below; if SMTP is
    # missing the API still issues tokens but logs a warning and (outside
    # production) surfaces the link in the API response for debugging.
    auth_require_email_verification: bool = False
    email_verification_ttl_hours: int = 24
    # Base URL of the frontend, used to build the verification link.
    web_base_url: str = "http://localhost:13500"

    # ── SMTP (transactional email) ──────────────────────────────────────
    # Leave smtp_host empty to disable email delivery (dev mode). Gmail
    # example:
    #   SMTP_HOST=smtp.gmail.com
    #   SMTP_PORT=587
    #   SMTP_USE_STARTTLS=true
    #   SMTP_USER=youraddress@gmail.com
    #   SMTP_PASSWORD=<16-char-app-password>
    #   SMTP_FROM=youraddress@gmail.com
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_starttls: bool = True
    smtp_use_ssl: bool = False  # mutually exclusive with starttls (use port 465)
    smtp_timeout_seconds: int = 10

    # ── Brute-force lockout ─────────────────────────────────────────────
    # Counter increments on every wrong password; on the Nth fail the
    # account is locked for `auth_lockout_minutes`. Counter resets on
    # successful login or when the lock expires.
    # ── Password reset («¿Has olvidado tu contraseña?») ─────────────────
    password_reset_ttl_minutes: int = 30

    auth_lockout_threshold: int = 4
    auth_lockout_minutes: int = 15

    # ── Per-user LLM keys ───────────────────────────────────────────────
    # Symmetric key (Fernet, base64-urlsafe 32 bytes) used to encrypt
    # user-supplied Gemini API keys at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty string = feature disabled (server falls back to the global key).
    app_encryption_key: str = ""

    # Daily call budget when a user is using the SHARED server key. Users
    # who configure their own key are not throttled here (their own quota
    # at Google applies). Reset rolls forward at the next UTC day.
    server_llm_daily_quota: int = 50

    # ── MFA / TOTP (Práctica 2 · 8.2) ───────────────────────────────────
    # Mandatory second factor for EVERY user. Can only be switched off
    # outside production (unit/e2e tests that predate MFA).
    mfa_required: bool = True
    mfa_issuer: str = "SOC Copilot"
    # Lifetime of the "password OK, waiting for TOTP" token.
    mfa_pending_ttl_seconds: int = 300
    mfa_pending_cookie_name: str = "soc_mfa_pending"

    # ── Wazuh SIEM integration (Práctica 2) ─────────────────────────────
    # PUSH: Wazuh integratord POSTs each alert to
    # /api/integrations/wazuh/webhook with ``Authorization: Bearer <token>``.
    # Empty token = webhook disabled (endpoint answers 503).
    #   Generate with: openssl rand -hex 32
    wazuh_webhook_token: str = ""
    # Alerts below this Wazuh rule.level are acknowledged but not stored.
    # Wazuh levels: 0-15 (7+ is the usual "worth a human look" threshold).
    wazuh_min_rule_level: int = 7
    # Max alerts accepted per webhook call (batch protection).
    wazuh_webhook_max_batch: int = 100
    # Per-IP bucket for the webhook (independent of the global UI bucket,
    # Wazuh can legitimately burst).
    wazuh_webhook_rate_limit: int = 600

    # PULL: SOC Copilot queries the Wazuh Indexer (OpenSearch) directly.
    # Leave the URL empty to disable pull mode.
    wazuh_indexer_url: str = ""  # e.g. https://wazuh.indexer:9200
    wazuh_indexer_user: str = ""
    wazuh_indexer_password: str = ""
    wazuh_indexer_index: str = "wazuh-alerts-*"
    # Path to the Wazuh root CA (root-ca.pem). If empty, TLS is verified
    # against the system store; set WAZUH_INDEXER_VERIFY_TLS=false only in
    # labs with self-signed certs.
    wazuh_indexer_ca_cert: str = ""
    wazuh_indexer_verify_tls: bool = True
    wazuh_indexer_timeout_seconds: int = 15
    # Max documents per pull.
    wazuh_pull_batch_size: int = 200
    # Background poller. 0 = disabled (only manual "Sincronizar ahora").
    wazuh_poll_interval_seconds: int = 0
    # First pull with no cursor looks back this many minutes.
    wazuh_pull_initial_lookback_minutes: int = 60

    @property
    def wazuh_push_enabled(self) -> bool:
        return bool(self.wazuh_webhook_token)

    @property
    def wazuh_pull_enabled(self) -> bool:
        return bool(self.wazuh_indexer_url)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def effective_cookie_secure(self) -> bool:
        return self.cookie_secure or self.is_production

    @property
    def effective_cookie_samesite(self) -> str:
        return "strict" if self.is_production else self.cookie_samesite

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]
        # Wildcards combined with credentialed cookies are unsafe — strip
        # them defensively even if someone sets API_CORS_ORIGINS=*.
        return [o for o in origins if o != "*"]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def validate_for_runtime(self) -> None:
        """Refuse to start with insecure defaults in production."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.jwt_secret in _INSECURE_JWT_SECRETS or len(self.jwt_secret) < 32:
            problems.append(
                "JWT_SECRET must be set to a strong (>=32 chars) value in production"
            )
        if self.postgres_password in _INSECURE_PG_PASSWORDS:
            problems.append("POSTGRES_PASSWORD must be rotated away from defaults")
        if not self.app_encryption_key:
            problems.append(
                "APP_ENCRYPTION_KEY is required to encrypt per-user secrets"
            )
        if not self.gemini_api_key:
            problems.append("GEMINI_API_KEY is required")
        if not self.cors_origins_list:
            problems.append("API_CORS_ORIGINS must list at least one explicit origin")
        for o in self.cors_origins_list:
            if not (o.startswith("https://") or o.startswith("http://localhost")):
                problems.append(
                    f"API_CORS_ORIGINS entry {o!r} must use https:// in production"
                )
        if not self.mfa_required:
            problems.append("MFA_REQUIRED must be true in production (MFA obligatorio)")
        if self.wazuh_webhook_token and len(self.wazuh_webhook_token) < 32:
            problems.append(
                "WAZUH_WEBHOOK_TOKEN must be >=32 chars (openssl rand -hex 32)"
            )
        if self.wazuh_indexer_url and not self.wazuh_indexer_url.startswith(
            "https://"
        ):
            problems.append("WAZUH_INDEXER_URL must use https:// in production")
        if problems:
            raise RuntimeError(
                "Refusing to start with insecure configuration:\n  - "
                + "\n  - ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_for_runtime()
    return settings
