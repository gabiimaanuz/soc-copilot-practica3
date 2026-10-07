# Seguridad — Estado actual

## Resumen

Cubre las mitigaciones aplicadas en fases 1–5 (desarrollo + despliegue
Hetzner) y los riesgos residuales pendientes de tratar antes o después
de la entrega del 25-05-2026. Estado a fecha 18/05/2026 con el sistema
en producción.

### Endurecimiento incorporado en fase 5

| Capa | Mitigación |
|------|------------|
| Transporte | Caddy 2 con TLS automático Let's Encrypt; HSTS preload (`max-age=63072000; includeSubDomains; preload`); HTTP/3 habilitado. |
| Cookies | `HttpOnly` + `Secure` + `SameSite=Strict` en producción (forzado por `effective_cookie_samesite`). |
| Headers globales | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: geolocation=(), microphone=(), camera=()`, eliminación de `Server` y `X-Powered-By`. |
| Reverse proxy | Caddy con `trusted_proxies static private_ranges` para que la API confíe XFF solo desde la red interna. |
| Validación arranque | `Settings.validate_for_runtime()` rechaza encender la API en producción si `JWT_SECRET`, `POSTGRES_PASSWORD`, `APP_ENCRYPTION_KEY`, `GEMINI_API_KEY` o `API_CORS_ORIGINS` quedan en valores por defecto, o si algún origen CORS no es `https://`. |
| Email verification | `AUTH_REQUIRE_EMAIL_VERIFICATION=true`. SMTP saliente vía Gmail con App Password (no contraseña real). Si SMTP falla, el registro NO se aborta — el token queda en BD y un admin puede marcarlo verificado o reenviar. En producción la API nunca expone el link en la respuesta JSON. |
| Anti-bruteforce | 4 intentos fallidos → bloqueo 15 minutos por cuenta. Contador se reinicia con login correcto o vencimiento. |
| Rate limit | Por IP del cliente (XFF respetado). Buckets adicionales en `/auth/check-email` (10/60s por IP) y `/auth/register` (3/h por email). |
| Servidor | UFW (22/80/443 only). fail2ban con jail `sshd`. SSH key-only, `PermitRootLogin no`, `AllowUsers soc`. `unattended-upgrades` para parches de seguridad. |
| Secretos | `.env` con permisos 600 propiedad del usuario `soc`. Copia offline en Windows. No commiteado (`.gitignore`). |
| Backups | Dump `pg_dump --clean --if-exists` diario en server (cron, 14 días retención) + tarea Windows que los descarga a `Documents/` (30 días retención). Snapshots Hetzner adicionales a nivel disco (7 días). |
| Toggle de registro | El flag `public_registration_enabled` se persiste en BD (`app_settings`) y se audita en cada cambio. El admin puede cerrarlo desde la UI tras una demo sin reiniciar nada. |

## Mitigaciones aplicadas

### Errores LLM no fugan información

- `LLMError` se subdivide en `LLMProviderError` y `LLMResponseError`.
- Routers `/api/explain`, `/api/recommend`, `/api/chat` capturan ambas y
  registran `logger.exception(...)` con el detalle real, devolviendo al
  cliente:
  - `502 AI provider error` si falló la llamada al proveedor.
  - `502 AI response could not be processed` si la respuesta no se pudo
    parsear/validar.
- Verificado por tests `test_*_provider_error_returns_generic_502` que
  inyectan errores con strings tipo `AIzaXXX`/`quota`/`internal-only` y
  comprueban que ninguno aparece en el body de la respuesta.

### Mitigación de prompt injection

- Logs del usuario se envuelven con `BEGIN_UNTRUSTED_LOG` / `END_UNTRUSTED_LOG`
  en `services/explainer.py` y `services/recommender.py`.
- Documentos recuperados del RAG se envuelven con `BEGIN_UNTRUSTED_KB` /
  `END_UNTRUSTED_KB` en `services/chat.py` (mitigación de RAG poisoning).
- Los `SYSTEM_PROMPT` instruyen explícitamente al modelo a:
  - Tratar el contenido entre delimitadores como **dato a analizar**,
    nunca como instrucciones a obedecer.
  - Identificar y reportar intentos de «ignora instrucciones previas»
    como posible prompt injection en el campo `reasoning`.
- En `recommender`, regla extra contra acciones destructivas: cualquier
  acción que toque firewall, IAM o borrado debe llevar prefijo
  `[REQUIERE APROBACIÓN HUMANA]` en `detail`. Verificado por test.

### Validación de entrada

| Campo | Regla |
|-------|-------|
| `ExplainRequest.log` | 1..20000 chars, rechazo whitespace-only |
| `ExplainRequest.source` | ≤200 chars |
| `ExplainRequest.model` | Allowlist (server-side) |
| `RecommendRequest.alert_id` | ≥1 si presente |
| `RecommendRequest.log` | ≤20000, no whitespace-only si no hay alert_id |
| `RecommendRequest.source` | ≤200 |
| `RecommendRequest.model` | Allowlist |
| `ChatMessage.role` | `Literal["user","assistant","system"]` |
| `ChatMessage.content` | 1..4000, rechazo whitespace |
| `ChatRequest.messages` | 1..30 mensajes |
| `ChatRequest.log_context` | ≤20000 |
| `ChatRequest.model` | Allowlist |
| `RegisterRequest.password` | 10..128 chars + política `check_password` (mayús, minús, dígito, símbolo, zxcvbn ≥ 2). |
| `RegisterRequest.email` | `EmailStr` (validador RFC 5322 + DNS heuristics) |
| `ChangePasswordRequest.new_password` | Misma política que `RegisterRequest.password` (admin reset). |
| `CreateUserRequest.password` | Misma política que `RegisterRequest.password` (admin create). |

### Rate limiting

- `app/middleware/ratelimit.py` implementa ventana deslizante por IP en
  memoria, con lock para entornos multi-thread.
- Aplicado a `/api/explain`, `/api/recommend`, `/api/chat`. NO afecta a
  `/api/health`, `/api/auth/*`, `/api/kb/status`, `/api/llm/models`,
  `/api/alerts*`.
- Variables:

  | Variable | Default |
  |----------|---------|
  | `RATE_LIMIT_ENABLED` | `true` |
  | `RATE_LIMIT_REQUESTS` | `20` |
  | `RATE_LIMIT_WINDOW_SECONDS` | `60` |

- Limitación: in-memory ⇒ no compartido entre procesos. En prod multi-worker
  se sustituirá el backing store por Redis (fase ≥5).

### Autenticación (fase 4)

- Cookie httpOnly `soc_session` con JWT HS256 firmado con `JWT_SECRET`.
- TTL configurable (`JWT_TTL_SECONDS`, default 3600s).
- `SameSite=Lax`. `Secure` flag vía `COOKIE_SECURE` (off en dev, on en prod).
- Aceptamos también `Authorization: Bearer <token>` para tests/clientes
  API.
- **JWT invalidable**: el token incluye claim `pv` (password_version del
  usuario). El middleware compara contra el valor actual en BD; si no
  coincide responde 401. El admin endpoint `users/{id}/password` y
  `users/{id}/role` incrementan ese contador, así que un reset forzado
  caduca todas las sesiones existentes del afectado en el siguiente
  request.
- **Auth state cross-tab** en frontend: `AuthProvider` escucha eventos
  `storage` y `focus` y revalida con el backend, así un logout en una
  pestaña se propaga al resto sin refresh manual.

Variables (todas en `.env.example`):

| Variable | Default | Notas |
|----------|---------|-------|
| `JWT_SECRET` | dev-only string | **Rotar antes de prod**: `openssl rand -base64 48` |
| `JWT_TTL_SECONDS` | 3600 | Sesión de 1 hora |
| `COOKIE_NAME` | `soc_session` | |
| `COOKIE_SECURE` | `false` | Pasar a `true` detrás de Caddy/HTTPS |

### Autorización (RBAC dinámico + ownership)

- Dos roles: `analyst` (default) y `admin`.
- **Primer usuario en registrarse** queda como admin. **Sin seed por
  defecto** (eliminado el antiguo `admin@soc.local`/`admin` que se
  creaba en `init_db`).
- **Permisos granulares**: cada endpoint admin usa `require_perm("clave")`
  consultando la tabla `role_permissions`. Si la tabla no tiene un
  override para esa pareja `(role, key)`, cae al default de la registry
  estática en `app/services/permissions.py`.
- **Permission `permissions.manage` lockeada**: el backend rechaza
  cualquier intento de cambiarla → un admin no puede quitarse a sí mismo
  la capacidad de gestionar permisos.
- Endpoints protegidos por sesión: `/api/explain`, `/api/recommend`,
  `/api/chat`, `/api/alerts*`, `/api/auth/me`. Todos devuelven 401 sin
  sesión.
- Endpoints protegidos por permiso: `/api/admin/*`. Devuelven 403 si el
  rol del actor no tiene la clave correspondiente.
- Endpoints públicos: `/api/health`, `/api/kb/status`, `/api/llm/models`,
  `/api/auth/{register,login,logout}`, `/api/docs`, `/api/openapi.json`.
- Filtros de ownership en `app/routers/alerts.py`:
  - Lista: `WHERE user_id = current_user.id` (admin sin filtro).
  - Detalle: `404` para no-owner (no `403`, evitamos leak de existencia).
- `/api/recommend` con `alert_id` ajeno: `404` para no-owner igualmente.

### Auditoría

- Tabla `audit_logs` append-only con FK `actor_id ON DELETE SET NULL`
  para que el rastro sobreviva a la eliminación del actor.
- Todas las acciones admin (create/delete/role-change/password-reset/
  permissions-update) se registran con `actor_id`, `actor_email`,
  `target_*`, IP del cliente y diff JSON en `details`.
- Visible en la UI bajo `/admin` → pestaña Auditoría con filtros por
  acción y actor. Read-only: no hay endpoint para borrar ni modificar
  filas.

### Allowlist de modelos LLM

- `Settings.gemini_chat_models_allowlist` define qué modelos puede pedir
  el cliente (default: `gemini-2.5-flash-lite, gemini-2.5-flash,
  gemini-2.0-flash-lite`).
- Pydantic valida `model` contra esa lista (422 si no).
- `GeminiAdapter._resolve_chat_model` valida también, defense in depth:
  si llega un modelo desconocido (bypass de validación), cae al default
  y loggea warning.
- `GET /api/llm/models` devuelve `{default, available}` para que el
  frontend no hardcodee la lista.

### Secretos no fugan

- `.env` está en `.gitignore`. Solo `.env.example` con placeholders se
  versiona.
- Verificación periódica:

  ```bash
  git log --all -p | grep -c "AIzaSy"   # ⇒ 0
  git ls-files | grep -E "(\.env$|secret|credential)"   # ⇒ vacío
  ```

- En contenedores los secretos viven en `Config.Env` (visible solo via
  `docker inspect`, no via HTTP).

## Práctica 2 — nuevos controles (05/10/2026)

- **MFA TOTP obligatorio** para todos los usuarios (RFC 6238, secreto
  cifrado con Fernet, anti-replay, códigos de recuperación hasheados,
  bloqueo compartido con la contraseña, arranque bloqueado en producción
  si `MFA_REQUIRED=false`). Detalle: [17-mfa-totp.md](17-mfa-totp.md).
- **Webhook Wazuh** autenticado con token compartido (comparación en
  tiempo constante, ≥32 caracteres en producción), rate limit propio y
  límites de tamaño. Detalle: [13-integracion-wazuh.md](13-integracion-wazuh.md#7-seguridad).
- **Informe PDF**: datos del analista delimitados como no confiables en el
  prompt; todo el texto escapado antes de ReportLab (sin inyección de
  markup). Detalle: [15-informe-incidente.md](15-informe-incidente.md#3-arquitectura).
- Riesgo residual: el TOTP no protege frente a phishing en tiempo real
  (AitM); WebAuthn/passkeys quedaría como mejora futura.

## Parches Recientes (Remediación Post-Fase-4)

Se han implementado correcciones específicas basadas en el reporte de vulnerabilidades:

1. **Prompt Injection en Explainer**: Se agregó sanitización redundante (`.replace()`) para remover cualquier secuencia de delimitadores `BEGIN_UNTRUSTED_LOG` y `END_UNTRUSTED_LOG` que el usuario intente falsificar en el texto del log.
2. **Timing Attacks en el Login**: Se estandarizó el tiempo de respuesta del endpoint `/api/auth/login`. Si el correo electrónico no existe en la BD, se ejecuta un hash bcrypt "dummy" con `hash_password(payload.password)` para igualar la carga de CPU, previniendo enumeración de usuarios.
3. **Catastrophic Backtracking (ReDoS)**: El regex cliente en `/logs` que extraía IPs (SRC/DST) sustituyó los wildcards codiciosos `.*?` por límites controlados `.{0,150}?`. Esto evita bloqueos del navegador si se inyectan líneas de log malformadas gigantescas.
4. **Denegación de Servicio por Paginación Nula**: El endpoint administrativo `/api/admin/users` fue fortificado con parámetros de paginación (`limit`, `offset`) para prevenir el colapso de memoria al listar conjuntos de datos extensos.

## Riesgos pendientes por fase

| Fase | Riesgo | Mitigación planeada |
|------|--------|---------------------|
| **5** (deploy) | Hardening VPS | SSH key only, ufw, fail2ban, auto-actualizaciones |
| **5** | TLS / certificados | Caddy 2 + Let's Encrypt automático |
| **5** | Secret management | Variables fuera del repo, gestor (Hetzner secrets / age / sops) |
| **5** | Backups Postgres | `pg_dump` cron + offsite |
| **5** | Rate limiter en multi-worker | Sustituir backing store por Redis (slowapi) |
| **5** | Real client IP | `ProxyHeadersMiddleware` en uvicorn + `forwarded_allow_ips` apuntando al IP de Caddy |
| **5** | Registro público + race condition | `AUTH_REGISTRATION_ENABLED=false` + admin seed CLI |
| **5** | `JWT_SECRET` aún el de dev | Rotar a `openssl rand -base64 48` antes de exponer |
| **5** | Chroma sin auth | En prod queda en red interna del compose, sin puertos expuestos |
| **6** | Guion del informe + demo | Plantilla en `roadmap.md` |

## Cosas no verificadas o aceptadas

- `npm audit` devuelve 2 moderate por `postcss <8.5.10` que viene
  vendored dentro de Next.js (`node_modules/next/node_modules/postcss`).
  Nuestro top-level es 8.5.11. El fix oficial degrada Next a 9.x →
  inaceptable. Riesgo real bajo: ese postcss procesa CSS del propio
  bundle de Next, no input de usuario. Revisar al subir Next.
- Rate limiter detrás de proxy: verificado en producción Caddy → API
  con `trusted_proxies static private_ranges` en el Caddyfile. La API
  ve la IP del cliente real, no la del contenedor de Caddy.
- `docker-compose.prod.yml` desplegado en Hetzner CPX22 desde
  18/05/2026. Smoke parcial OK (login, chat con RAG, registro con
  verificación email, toggle de registro). Smoke E2E con un compañero
  del grupo todavía pendiente — recomendado antes de la demo.
- SMTP Gmail App Password: limitado a ~500 emails/día. Para una
  instalación a más usuarios convendría migrar a un servicio dedicado
  (Brevo, Resend con dominio propio, Amazon SES). Documentado como
  mejora post-entrega.
- DuckDNS como proveedor DNS: aceptable para una práctica académica, no
  para una operación seria (sin records DNS personalizables, dependes
  de un servicio gratuito de terceros). Sustituir por un dominio propio
  está como item baja prioridad en el roadmap.

## Pruebas de seguridad recomendadas antes de cada release

```bash
# 1. Endpoints protegidos siguen exigiendo auth
for ep in /api/explain /api/recommend /api/chat /api/alerts; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST http://localhost:8080$ep -d '{}' -H "Content-Type: application/json")
  [[ "$code" == "401" ]] || echo "FAIL $ep → $code"
done

# 2. Sanitización de errores LLM no fuga claves
docker compose exec api python -c "
import app.services.llm as m
class P(m.LLMAdapter):
    def generate_json(self,p,*,schema,system=None,temperature=0.2,model=None):
        raise m.LLMProviderError('AIzaSy_FAKE quota internal')
    def generate_text(self,p,*,system=None,temperature=0.2,model=None):
        raise m.LLMProviderError('AIzaSy_FAKE')
    def embed(self,t): return []
m._singleton = P()
from fastapi.testclient import TestClient
from app.main import app
from app.middleware.auth import get_current_user
from app.models import User, UserRole
app.dependency_overrides[get_current_user] = lambda: User(id=1,email='t@e.com',hashed_password='x',role=UserRole.ADMIN)
r = TestClient(app).post('/api/explain', json={'log':'x'})
assert 'AIza' not in r.text
print('sanitization OK')
"

# 3. Allowlist de modelos rechaza valores fuera
curl -sS -o /dev/null -w "model fuera → %{http_code}\n" \
  -X POST http://localhost:8080/api/explain \
  -H "Content-Type: application/json" \
  -d '{"log":"x","model":"gemini-2.5-pro"}'    # → 422
```
