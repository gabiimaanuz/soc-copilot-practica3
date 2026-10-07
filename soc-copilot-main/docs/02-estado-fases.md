# Estado del proyecto y fases completadas

## Estado general

El proyecto se encuentra al cierre del **ciclo de hardening admin
post-fase-4**. Existe una versión local ejecutable con Docker Compose,
backend FastAPI con auth JWT y RBAC dinámico (matriz de permisos editable
por admin), frontend Next.js 15 con header global persistente, panel
admin con cuatro pestañas (usuarios/roles/permisos/auditoría), perfil de
usuario, analizador de logs cliente con filtros de red, PostgreSQL para
persistencia, ChromaDB con base de conocimiento RAG (MITRE ATT&CK + OWASP
Top 10) y selector de modelo LLM con allowlist en backend.

**Fechas:** inicio 25-abril-2026 · entrega práctica 25-mayo-2026.

## Fase 0: base del proyecto · ✅ completada

- Estructura de monorepo con `apps/api`, `apps/web`, `infra` y `docs`.
- Dockerfiles para backend (Python 3.12) y frontend (Node 22).
- `infra/docker-compose.yml` con servicios `postgres`, `chroma`, `api`, `web`.
- `infra/docker-compose.prod.example.yml` plantilla para Hetzner (sin
  puertos públicos, Caddy 2 con TLS automático).
- CI en GitHub Actions con jobs api / e2e / web.
- Variables de entorno documentadas en `.env.example`.
- `.gitattributes` (LF) + `.gitignore` cubriendo `.env`, lockfiles, etc.

## Fase 1: Alert Explainer · ✅ completada

- `POST /api/explain`.
- Servicio backend `app/services/explainer.py`.
- Adaptador LLM provider-agnostic en `app/services/llm.py`
  (`LLMAdapter` + `GeminiAdapter` actual).
- Esquemas Pydantic con validación estricta (longitud, no whitespace,
  modelo dentro del allowlist).
- UI `/alerts` con 3 ejemplos predefinidos y resultado con badge de riesgo.

Salida generada por la API:

- `summary` en lenguaje claro.
- `risk_level` ∈ {low, medium, high, critical}.
- `mitre_techniques` en formato `T####` o `T####.###`.
- `reasoning` didáctico para junior.

## Fase 2: Next Step Recommender + persistencia · ✅ completada

- `POST /api/recommend` con dos modos: por `alert_id` (carga contexto desde
  DB) o por `log` directo (no persiste).
- `GET /api/alerts` paginado y `GET /api/alerts/{id}` con recomendaciones
  anidadas.
- Modelos SQLAlchemy `Alert` y `Recommendation` (FK con `ON DELETE CASCADE`).
- Migraciones gestionadas por **Alembic** (`apps/api/alembic/versions/`).
  `init_db()` ejecuta `alembic upgrade head` en Postgres y hace
  `alembic stamp head` sobre bases legacy creadas con `create_all` para
  migrar sin pérdida. SQLite (sólo tests) sigue usando `create_all`.
- UI `/respond` y `/history`.

## Fase 3: RAG + Chat IA · ✅ completada

- Script idempotente `apps/api/scripts/ingest_kb.py` que descarga el bundle
  STIX de MITRE ATT&CK Enterprise, extrae técnicas vigentes y las combina
  con OWASP Top 10 2025 hardcodeado. Embeddings en lotes con backoff
  exponencial para sobrevivir al rate limit free-tier.
- Coleccion ChromaDB `soc_kb` con ~700 docs (691 MITRE + 10 OWASP en
  estado actual).
- Servicio `app/services/rag.py` con `Retriever` y diagnóstico `kb_status`.
- Servicio `app/services/chat.py` con orquestación retrieval + LLM,
  delimitadores `BEGIN/END_UNTRUSTED_KB` y `BEGIN/END_UNTRUSTED_LOG`
  contra prompt injection y RAG poisoning.
- `POST /api/chat`, `GET /api/kb/status`, `GET /api/llm/models`.
- UI `/chat` con citas clicables a attack.mitre.org y owasp.org.
- Selector de modelo (`gemini-2.5-flash-lite`, `gemini-2.5-flash`, etc.)
  con allowlist server-side y persistencia en `localStorage`.

## Fase 4: Auth + RBAC + tests E2E · ✅ completada

- Modelo `User` con rol `analyst` / `admin`. `Alert.user_id` como FK
  nullable para no romper alertas legacy.
- bcrypt + PyJWT HS256 con TTL 1h, cookie `soc_session` httpOnly +
  SameSite=Lax (Secure controlado por `COOKIE_SECURE`).
- Endpoints `/api/auth/{register, login, logout, me}`.
- Primer registro = admin, resto = analyst.
- Endpoints LLM y de alertas exigen sesión válida (401 si no).
- Ownership: analysts ven sólo sus alertas, admins ven todo (incluido
  legacy ownerless). 404 a no-owner para no leak existencia.
- Suite de tests: 69 unit + 2 E2E (Postgres real en CI vía
  `services.postgres`).
- Frontend: `<AuthProvider>`, `useAuth`, `useRequireAuth`, página `/login`
  con login + register, badge de usuario en cada cabecera.

## Ciclo post-fase-4: admin avanzado + UX · ✅ completado

Iteración de hardening y producto sin cambio de versión mayor de roadmap.

### Backend

- **`User` extendido**: campos `name`, `last_name`, `password_version`.
- **Eliminado el seed `admin@soc.local`/`admin`** que creaba el `init_db()`
  inicial. El primer registro vía `/api/auth/register` sigue siendo
  promovido a admin automáticamente, así que no hay credenciales por
  defecto que filtrar a producción.
- **JWT invalidable**: el token lleva claim `pv` (password_version) y el
  middleware lo compara con `User.password_version`. Reset de contraseña
  o cambio de rol bumpea el contador → caduca todas las sesiones
  emitidas previamente.
- **Audit log inmutable**: tabla `audit_logs` (helper
  `services/audit.py::log_audit`) registra acciones admin (create/delete/
  role change/password reset/permissions update) con actor, target, IP y
  diff JSON.
- **RBAC dinámico**: tabla `role_permissions` + registry estática en
  `services/permissions.py`. Cada endpoint admin usa
  `require_perm("clave")`; admin puede activar/desactivar permisos por
  rol desde la UI. La permission `permissions.manage` está marcada como
  `locked=True` para evitar lockout.
- **Endpoints admin nuevos**: `POST /api/admin/users`, `DELETE
  /api/admin/users/{id}`, `PUT /api/admin/users/{id}/role`, `GET
  /api/admin/audit`, `GET/PUT /api/admin/permissions`.
- **Edición de perfil**: `PUT /api/auth/me` permite a cualquier usuario
  autenticado modificar `name`, `last_name`, `email` (con check de
  unicidad).
- **`EmailStr` restaurado** en register/login (regresión que se había
  introducido sustituyendo por `pattern`).

### Frontend

- **`GlobalHeader` sticky** (`components/AuthGate.tsx`) montado en
  `app/layout.tsx`: presente en todas las páginas excepto `/login`, con
  brand → home, botón **← Inicio** (oculto en `/`), badge con nombre
  completo + email + rol + botón Salir. El nombre actúa como link a
  `/profile`.
- **Cross-tab auth sync**: `AuthProvider` escucha eventos `storage` y
  `focus` y hace `refresh()`. Logout en una pestaña echa a las demás sin
  necesidad de refrescar manualmente.
- **`useRequireAuth`** ahora devuelve flag `ready`; cada página
  autenticada renderiza un placeholder "Verificando sesión..." mientras
  no hay confirmación, evitando que el formulario sea interactivo entre
  el logout y la redirección.
- **`/admin`** rediseñado en cuatro pestañas:
  - *Usuarios*: tabla con selector de rol inline, modal de creación,
    modal de cambio de password, eliminación. Bloquea acciones sobre uno
    mismo cuando aplica.
  - *Roles*: tarjetas descriptivas con conteo de usuarios por rol.
  - *Permisos*: matriz editable (checkboxes) con filas baseline
    informativas y filas configurables. `Guardar cambios` envía un
    diff y queda registrado en auditoría.
  - *Auditoría*: tabla cronológica inversa con filtros por acción y
    actor, paginación 100/pág.
- **`/profile`**: edición de nombre, apellidos y email con feedback de
  éxito/error. Tras guardar, llama `auth.refresh()` para que el header
  se actualice solo.
- **`/logs`**: analizador 100% cliente. Carga `.log/.txt/.csv`,
  paginación con tamaño seleccionable (10/50/100/150), filtros de red:
  IP origen/destino (substring), puerto origen/destino (exacto), MAC
  (substring), protocolo (dropdown TCP/UDP/ICMP/HTTPS/HTTP/SSH/DNS/FTP/
  SMTP/TLS/ARP), búsqueda libre, errores de auth, errores HTTP 4xx/5xx,
  rango temporal heurístico. Cuatro estrategias de parsing en cascada
  (iptables `SRC=/DST=/SPT=/DPT=`, flecha `IP:port → IP:port`, sshd
  `from <ip> port <n>`, fallback "1ª IP origen / 2ª IP destino"). Las
  líneas seleccionadas viajan a `/alerts?import=true` por
  `sessionStorage`.

### Tooling

- **Generador de logs de prueba** `scripts/gen_sample_logs.py`: crea
  `apps/web/public/sample_{small,medium,large}.log` (~28 / ~500 / ~5000
  líneas) con seed fija y mezcla realista de SSH brute-force, port
  scans, web attacks, exfiltración, ICMP, DNS, DHCP, impossible travel
  y ruido benigno.
- **Backup script + guía** en `backup-soc-copilot/`: dump de Postgres,
  tar del volumen Chroma, tar del código, `DEPLOY.md` con pasos para
  desplegar en otra máquina (Docker Desktop + restore + first-user-as-
  admin).

## Hardening transversal aplicado

| Hardening | Fase | Estado |
|-----------|------|--------|
| Sanitización de errores LLM (502 genérico, log interno) | 2 | ✅ |
| Delimitadores anti prompt-injection en explain/recommend | 2 | ✅ |
| Rate limit en memoria por IP (configurable) | 2 | ✅ |
| Compose dev vs prod separados con comentarios | 2 | ✅ |
| Validadores estrictos de schemas (longitud, whitespace, allowlist) | 2 | ✅ |
| Frontend deps al día (Next 15.5, postcss 8.5.11, etc.) | 2 | ✅ |
| Allowlist de modelos LLM + override por request | 3 | ✅ |
| Delimitadores anti RAG-poisoning en chat | 3 | ✅ |
| Logs lifecycle: tests + scripts montados en compose | 4 | ✅ |
| ESLint flat config (sustituye `next lint` deprecado) | 4 | ✅ |
| `.env.example` documenta `JWT_*` y `COOKIE_*` | 4 | ✅ |
| CI: `ruff check app tests` + `npm run lint` + `npm audit` | 4 | ✅ |
| Mitigación de ReDoS (Regex wildcard cap) | post-fase-4 | ✅ |
| Normalización de tiempos en Auth (Timing Attack) | post-fase-4 | ✅ |
| Paginación forzada en lista de usuarios admin | post-fase-4 | ✅ |
| Sanitización redundante contra Prompt Injection en Explainer | post-fase-4 | ✅ |


## Fases pendientes

### Fase 4.5: dashboard analítico — ✅ completada

Detalle en [roadmap.md](roadmap.md#fase-45--checklist-dashboard-analítico).
Página `/dashboard` con KPIs, distribución por riesgo, serie temporal
30d y top técnicas MITRE, alimentada por un nuevo `GET /api/stats` que
respeta el ownership existente. Recharts integrado y renderizando gráficas interactivas en frontend. Suma al 15% de UX de la rúbrica y aporta material visual para la demo.

### Fase 5: despliegue Hetzner — ✅ completada (18/05/2026)

Producción operativa en <https://soc-copilot.duckdns.org>. Detalles
operativos completos en [operations.md](operations.md). Resumen del
estado entregado:

| Capa | Estado |
|------|--------|
| VPS Hetzner CPX22 (Nuremberg, ~8,5 €/mes con backups) | ✅ |
| Dominio DuckDNS apuntando al VPS | ✅ |
| `JWT_SECRET`, `APP_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `NEXTAUTH_SECRET` rotados a valores producción (`openssl rand`) | ✅ |
| `infra/docker-compose.prod.yml` desplegado a partir del example, con el bloque `web.build.args` forwardeando `NEXT_PUBLIC_API_URL` para que Next lo embeba en el bundle | ✅ |
| Caddy 2 con `PUBLIC_DOMAIN=soc-copilot.duckdns.org` y `ACME_EMAIL` reales → certs Let's Encrypt automáticos, HTTP/3, HSTS preload | ✅ |
| `cookie_secure=true`, `APP_ENV=production` (la API se niega a arrancar con defaults inseguros) | ✅ |
| Hardening VPS: SSH key-only, `PermitRootLogin no`, `AllowUsers soc`, UFW 22/80/443, fail2ban activo, `unattended-upgrades` para parches de seguridad | ✅ |
| Backups Postgres: `cron.daily` con dump `pg_dump --clean --if-exists` comprimido, retención 14 días en `/var/backups/soc-copilot/` | ✅ |
| Backups offline: tarea programada en Windows que descarga los dumps a `Documents/soc-copilot-db-backups/` con retención 30 días | ✅ |
| KB ingestada en Chroma de producción: 697 técnicas MITRE Enterprise + 10 OWASP 2025 = **707 docs** | ✅ |
| SMTP cableado (Gmail App Password) para verificación de email en `/auth/register` | ✅ |
| Toggle admin para abrir/cerrar `ALLOW_PUBLIC_REGISTRATION` desde UI sin redeploy (tabla `app_settings`, migración 0004) | ✅ |
| Manual de operaciones en español (`docs/operations.md`) con pre-flight checklist, troubleshooting típico, gestión de migraciones y recipes de TestClient para tracebacks ASGI | ✅ |

CD on tag queda como mejora opcional post-entrega — actualmente el
deploy es `bash /opt/soc-copilot/scripts/deploy.sh` sobre SSH, con el
checklist documentado.

### Fase 6: informe + presentación — pendiente

- Informe PDF profesional siguiendo la rúbrica (vale 20% de la nota).
- Presentación oral 10 min con demo en vivo en Hetzner.
- URL pública + URL repo + PDF en campus virtual.

## Estado de calidad

Snapshot del último commit en `main`:

| Métrica | Valor |
|---------|-------|
| Tests backend (unit) | 67 passed (auth, byo_llm, logging, migrations, smoke) |
| Tests backend (E2E con Postgres real) | 7 passed (e2e + e2e_quota + stats) |
| ruff (`app` + `tests` + `scripts`) | clean |
| ESLint flat config (frontend) | 0 errors / 0 warnings |
| `npm audit --audit-level=high` | 0 critical, 0 high (2 moderate aceptados, ver security.md) |
| TypeScript `tsc --noEmit` | clean |
| `next build` | 9 rutas compiladas |
| GitHub Actions | últimos runs success |
