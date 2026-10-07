# SOC Copilot — Handoff para otra IA

> Documento autocontenido. Pégalo entero al inicio de una conversación con
> otra IA para darle todo el contexto del proyecto sin que tenga que leer
> el repo.

---

## 1. Contexto académico

- **Asignatura:** Práctica 1 — Ciberseguridad con IA, Módulo de
  Ciberseguridad Avanzada (Curso 2026).
- **Línea elegida:** Blue Team.
- **Producto:** *SOC Copilot* — asistente con IA para analistas SOC
  junior.
- **Equipo:** 5 personas → la rúbrica exige "alcance completo"
  (modularidad, documentación, funcionalidades diferenciadas por
  miembro).
- **Fechas:** inicio 2026-04-25, entrega 2026-05-25.
- **Entregables exigidos:** web dashboard funcional, repo GitHub, deploy
  en Hetzner Cloud, informe PDF profesional, demo oral de 10 min.
- **Rúbrica:** 30% funcionalidad · 20% informe · 15% UX dashboard ·
  15% deploy Hetzner · 10% calidad repo · 10% roadmap Práctica 2.

---

## 2. Qué hace el producto

Cuatro capacidades sobre la misma base auth/RBAC:

1. **Alert Explainer** (`POST /api/explain`, UI `/alerts`): se pega un
   log, devuelve `summary`, `risk_level` (low/medium/high/critical),
   `mitre_techniques` (T####), `reasoning` didáctico.
2. **Next Step Recommender** (`POST /api/recommend`, UI `/respond`):
   recomendaciones accionables sobre una alerta ya analizada. Dos modos:
   por `alert_id` (persiste) o por `log` directo (no persiste). Regla
   anti-destrucción: acciones drásticas llevan prefijo `[REQUIERE
   APROBACIÓN HUMANA]`.
3. **Chat IA con RAG** (`POST /api/chat`, UI `/chat`): conversación con
   citas verificables sobre MITRE ATT&CK Enterprise + OWASP Top 10 2025.
   707 docs en ChromaDB.
4. **Dashboard analítico + panel admin** (`/dashboard`, `/admin`): KPIs,
   distribución por riesgo, serie temporal 30d, top técnicas MITRE,
   gestión de usuarios, RBAC dinámico (matriz editable), auditoría
   inmutable.

Hay además un analizador de logs 100% cliente en `/logs` con filtros de
red (IP/puerto/MAC/protocolo/auth-fail/4xx-5xx), paginación, y
selección que viaja a `/alerts?import=true` por `sessionStorage`.

---

## 3. Stack y arquitectura

```
                 ┌─────────────────┐
                 │     Caddy 2     │  TLS automático (Let's Encrypt)
                 │  HTTP/2 + HTTP/3│  HSTS preload, security headers
                 └────────┬────────┘
            /api/* │            │ /*
                   ▼            ▼
          ┌─────────────┐  ┌─────────────┐
          │  FastAPI    │  │  Next.js 15 │
          │  Uvicorn    │  │ (standalone)│
          └──┬───┬───┬──┘  └─────────────┘
             │   │   └─── ChromaDB 0.5.23 (RAG MITRE+OWASP, 707 docs)
             │   └─────── Gemini API (chat + embeddings)
             └─────────── Postgres 16 (users, alerts, recs, audit, app_settings, role_permissions)
```

| Capa | Tecnología |
|------|------------|
| Backend | FastAPI 0.115 + Uvicorn 0.32, Python 3.12, Pydantic v2 |
| ORM + migraciones | SQLAlchemy 2 + Alembic 1.14 |
| DB | PostgreSQL 16-alpine |
| Vector store | ChromaDB 0.5.23, embeddings `gemini-embedding-001` (3072d) |
| LLM | Gemini `2.5-flash-lite` / `2.5-flash` (allowlist server-side) |
| Auth | PyJWT HS256 + bcrypt + cookie httpOnly + claim `pv` (password_version) para invalidar sesiones |
| Frontend | Next.js 15.5 + React 19 + TS 5.9 + Tailwind 3.4 + Recharts |
| Reverse proxy | Caddy 2 |
| Hosting | Hetzner CPX22 (3 vCPU / 4 GB / 80 GB NVMe, Nuremberg, ~8,5 €/mes con backups) |
| Dominio | DuckDNS `soc-copilot.duckdns.org` |
| CI | GitHub Actions: ruff + pytest unit + pytest e2e (Postgres service) + ESLint + tsc + next build + npm audit |

Repo monorepo: `apps/api`, `apps/web`, `infra`, `docs`, `scripts`.

---

## 4. Modelo de datos

```
USERS ─< ALERTS ─< RECOMMENDATIONS
USERS ─< AUDIT_LOGS
ROLE_PERMISSIONS (matriz role × permission_key)
APP_SETTINGS (toggles runtime, p.ej. ALLOW_PUBLIC_REGISTRATION)
```

Claves:
- `users.password_version` se bumpea en reset password o cambio de rol;
  el JWT lleva `pv` y el middleware rechaza tokens stale → invalida
  sesiones sin necesidad de blacklist.
- `alerts.user_id` nullable: alertas pre-fase-4 quedan sin owner y solo
  las ve admin. Ownership: analyst ve las suyas, admin ve todo, 404 a
  no-owner para no leak existencia.
- `recommendations.alert_id` con `ON DELETE CASCADE`.
- `audit_logs` append-only, `actor_id` con `ON DELETE SET NULL`.
- `role_permissions` guarda solo **desviaciones** sobre la registry
  estática en `services/permissions.py`. Permission `permissions.manage`
  marcada `locked=True` para evitar lockout.

Migraciones: Alembic. `init_db()` ejecuta `alembic upgrade head` en
Postgres y hace `alembic stamp head` sobre DBs legacy creadas con
`create_all`. SQLite solo en tests.

---

## 5. Endpoints (resumen)

| Método | Path | Auth | Notas |
|--------|------|------|-------|
| GET | `/api/health` | público | smoke |
| GET | `/api/llm/models` | público | allowlist + default |
| GET | `/api/kb/status` | público | conteo MITRE/OWASP |
| POST | `/api/auth/register` | público | primer usuario = admin, verificación email SMTP |
| POST | `/api/auth/login` | público | set-cookie httpOnly, normalización de tiempos anti-timing |
| POST | `/api/auth/logout` | público | clear-cookie |
| GET/PUT | `/api/auth/me` | sesión | edición de name/last_name/email |
| POST | `/api/explain` | sesión | rate-limit, persiste con user_id |
| POST | `/api/recommend` | sesión | rate-limit, `alert_id` o `log` |
| POST | `/api/chat` | sesión | rate-limit, RAG sobre `soc_kb` |
| GET | `/api/alerts` | sesión | paginado, ownership |
| GET | `/api/alerts/{id}` | sesión | con recommendations |
| GET | `/api/stats` | sesión | KPIs dashboard, cache 60s |
| GET/POST/DELETE | `/api/admin/users[...]` | `users.*` perms | crear/borrar/cambiar rol/reset password |
| GET | `/api/admin/audit` | `audit.view` | append-only, filtros |
| GET/PUT | `/api/admin/permissions` | `permissions.manage` | matriz role × key, bulk con diff |

Detalle en `docs/06-api-reference.md`.

---

## 6. Hardening aplicado (lo que está hecho)

- Allowlist server-side de modelos LLM + override por request validado
  en pydantic y en el adapter (defense in depth).
- Delimitadores `BEGIN/END_UNTRUSTED_LOG` y `BEGIN/END_UNTRUSTED_KB`
  contra prompt injection y RAG poisoning. System prompt instruye al
  modelo a tratar ambos bloques como dato.
- Recommender con regla anti-acciones-destructivas (prefijo "REQUIERE
  APROBACIÓN HUMANA").
- `LLMProviderError` / `LLMResponseError` → 502 genéricos al cliente,
  detalle solo en logs internos (no se filtra modelo/quota/stack).
- Sanitización redundante anti prompt injection en Explainer.
- Rate limit in-memory por IP, sliding window con threading lock, lee
  XFF detrás de Caddy (`trusted_proxies static private_ranges`).
- ReDoS: cap de wildcard en regex.
- Timing attack: normalización de tiempos en `/auth/login`.
- JWT invalidable por bump de `password_version` (claim `pv`).
- Audit log inmutable con diff JSON para todas las acciones admin
  (create/delete/role/password/permissions).
- bcrypt + cookie httpOnly + SameSite=Lax (Strict en prod) + Secure si
  `COOKIE_SECURE=true`.
- `APP_ENV=production` valida que no haya secretos por defecto y se
  niega a arrancar si los encuentra.
- VPS hardening: SSH key-only, `PermitRootLogin no`, `AllowUsers soc`,
  UFW 22/80/443, fail2ban (jail sshd), unattended-upgrades, swap 2 GB.
- Backups Postgres `cron.daily` con `pg_dump --clean --if-exists | gzip`,
  retención 14d en VPS + 30d en Windows offline.
- Caddy: HTTPS auto, HTTP/3, HSTS preload, CSP, X-Content-Type-Options,
  X-Frame-Options, Referrer-Policy, Permissions-Policy.

---

## 7. Estado por fases

| Fase | Hito | Estado |
|------|------|--------|
| 0 | Setup repo + Docker Compose | ✅ |
| 1 | Alert Explainer | ✅ |
| 2 | Next Step Recommender + Postgres + Alembic | ✅ |
| 3 | RAG + Chat IA (MITRE+OWASP en Chroma) | ✅ |
| 4 | Auth JWT cookie + RBAC + E2E | ✅ |
| 4.5 | Dashboard analítico (`/dashboard` + `/api/stats`) | ✅ |
| 5 | Hetzner + DuckDNS + Caddy + backups + SMTP + toggle registro | ✅ |
| 6 | Informe PDF + demo 10 min | ⏳ pendiente |

**Producción operativa en https://soc-copilot.duckdns.org desde 2026-05-18.**

Snapshot de calidad sobre `main`:
- Backend unit tests: 67 passed (auth, byo_llm, logging, migrations, smoke)
- Backend E2E con Postgres real: 7 passed
- ruff (`app` + `tests` + `scripts`): clean
- ESLint flat config: 0 errors / 0 warnings
- `npm audit --audit-level=high`: 0 critical, 0 high (2 moderate aceptados, ver `docs/security.md`)
- `tsc --noEmit`: clean
- `next build`: 9 rutas compiladas
- GitHub Actions: últimos runs verdes

---

## 8. Qué queda

**Fase 6 (deadline 2026-05-25, ~6 días):**
- Informe PDF profesional según rúbrica (portada, índice, resumen
  ejecutivo, problema, arquitectura, evidencias fase a fase, guía
  deploy, manual de uso, conclusiones, roadmap Práctica 2 con ≥5
  funcionalidades).
- Demo oral 10 min con stack en Hetzner; plan B con capturas/video.
- Entregar URL pública + URL repo + PDF en campus virtual.

---

## 9. Decisiones de diseño no obvias (para entender el código)

- **Provider-agnostic LLM**: `LLMAdapter` abstracto, hoy solo
  `GeminiAdapter`. Añadir Claude/OpenAI/Ollama = escribir un sibling.
- **`init_db()` con bridge Alembic**: detecta DBs legacy creadas con
  `create_all` y las marca con `alembic stamp head` para migrar sin
  pérdida.
- **`recommend` con dos modos** por diseño: el modo `log` sirve para
  preview sin polucionar el histórico.
- **Header global montado en `app/layout.tsx`** vía `<AuthGate>` que
  decide qué renderizar según ruta y sesión; `/login` queda fuera.
- **Cross-tab auth sync** con eventos `storage` y `focus` → logout en
  una pestaña echa al resto sin polling.
- **Permission registry estática + tabla con desviaciones** evita seed
  inicial y permite reset trivial: borrar la tabla.
- **`/logs` 100% cliente** porque el parser de logs no debe gastar
  cuota Gemini ni tocar el server; solo viajan al backend las líneas
  que el analista selecciona.

---

## 10. Roadmap para Práctica 2 (≥5 exige la rúbrica)

Documentado en `docs/roadmap.md`. Las 10 propuestas actuales:

1. Integración con SIEM real (Wazuh / Elastic / Splunk).
2. Multi-tenant + RBAC ampliado (workspaces, roles custom, scoping).
3. Modelo fine-tuned para pre-clasificar logs antes de Gemini.
4. Feedback loop del analista (útil/no útil → fine-tune incremental).
5. Multi-LLM con A/B (Claude + OpenAI + Ollama local, métrica calidad).
6. Export PDF firmado de informes de incidente (timeline + IOCs).
7. Threat intel (MISP / OpenCTI) para enriquecer IPs/hashes/dominios.
8. Escalabilidad: rate limit en Redis, Celery, réplica Postgres.
9. Hardening: 2FA, password reset self-service, secrets manager.
10. Observabilidad: OpenTelemetry + Prometheus + Grafana + alerting.

---

## 11. Cómo arrancar el proyecto en local

```bash
git clone git@github.com:f3l0X/soc-copilot.git
cd soc-copilot
cp .env.example .env       # rellenar GEMINI_API_KEY + secretos
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml --env-file .env \
  exec api python -m scripts.ingest_kb     # ~5 min, puebla Chroma
```

Abrir http://localhost:13500. Primer registro = admin automático.
Detalle en `docs/01-instalacion-local.md`.

---

## 12. Archivos clave para una IA que llegue nueva

- `docs/02-estado-fases.md` — historia completa
- `docs/03-arquitectura.md` — código componente por componente
- `docs/06-api-reference.md` — endpoints con request/response
- `docs/operations.md` — runbook prod (Hetzner, Caddy, backups, troubleshooting)
- `docs/security.md` + `docs/vulnerability_report.md` — postura de seguridad
- `docs/roadmap.md` — fases, riesgos, mejoras Práctica 2
- `apps/api/app/services/*.py` — lógica de negocio
- `apps/api/alembic/versions/` — migraciones
- `infra/docker-compose.prod.example.yml` — referencia deploy
