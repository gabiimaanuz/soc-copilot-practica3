# Referencia de API

> Generada a partir del estado actual del backend. Para spec interactivo
> en vivo, abrir <http://localhost:8080/docs> (Swagger UI auto-generado
> por FastAPI).

Todos los endpoints viven bajo prefijo `/api`.

## Convenciones

- **Auth**: cookie httpOnly `soc_session` (preferido) o
  `Authorization: Bearer <jwt>`. Detalle en
  [security.md](security.md#autenticación-fase-4).
- **Rate limit**: solo en endpoints LLM. Detalle en
  [security.md](security.md#rate-limiting).
- **Errores LLM**: 502 con detail genérico (`AI provider error` /
  `AI response could not be processed`). El mensaje real se loggea
  internamente.
- **Validación**: `422` con detail Pydantic estándar.

## Endpoints públicos

### `GET /api/health`

Smoke. Sin auth, sin rate limit.

```json
{"status": "ok"}
```

### `GET /api/llm/models`

Devuelve el modelo por defecto y el allowlist permitido al cliente.

```json
{
  "default": "gemini-2.5-flash-lite",
  "available": ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash-lite"]
}
```

### `GET /api/kb/status`

Diagnóstico de la knowledge base. Errores se mapean a 503.

```json
{"total": 701, "mitre": 691, "owasp": 10, "unknown": 0}
```

## Auth

### `POST /api/auth/register`

Body:

```json
{"name": "Alice", "email": "user@example.com", "password": "min8chars"}
```

- 201: usuario creado. **Primer registro = admin**, resto = analyst.
- 409: email ya existe.
- 422: email inválido (validación `EmailStr`) o password <8 chars o
  `name` <2 chars.

Respuesta (`UserMe`):

```json
{
  "id": 1,
  "name": "Alice",
  "last_name": "",
  "email": "user@example.com",
  "role": "admin",
  "created_at": "2026-04-27T15:46:39.497Z"
}
```

### `POST /api/auth/login`

Body:

```json
{"email": "user@example.com", "password": "..."}
```

- 200: emite `Set-Cookie: soc_session=<jwt>; HttpOnly; SameSite=Lax`.
- 401: credenciales inválidas (no distingue email vs password).

Respuesta:

```json
{
  "user": {"id": 1, "email": "...", "role": "admin", "created_at": "..."},
  "expires_at": "2026-04-27T16:46:39.762Z"
}
```

### `POST /api/auth/logout`

Limpia la cookie. 204 No Content.

### `GET /api/auth/me`

Devuelve el usuario autenticado.

- 200: `UserMe` (incluye `name`, `last_name`, `email`, `role`).
- 401: sin sesión / token inválido / expirado / `pv` desfasado tras
  reset.

### `PUT /api/auth/me`

Body (todos los campos opcionales; envía solo lo que cambias):

```json
{"name": "Alice", "last_name": "Smith", "email": "alice@new.com"}
```

- 200: `UserMe` actualizado.
- 401: sin sesión.
- 409: el `email` propuesto ya está en uso por otro usuario.
- 422: `name` <2 chars / email inválido.

No bumpea `password_version`: cambiar email o nombre **no** invalida tu
sesión.

## Alert Explainer

### `POST /api/explain`

Auth: requerida. Rate-limited.

Body:

```json
{
  "log": "Apr 25 18:42:31 srv-01 sshd[2342]: Failed password for root from 91.234.56.78",
  "source": "auth.log",
  "model": "gemini-2.5-flash-lite"
}
```

Validación:

- `log`: 1..20000 chars, no whitespace-only.
- `source`: opcional, ≤200 chars.
- `model`: opcional, debe estar en allowlist.

Respuesta `200`:

```json
{
  "id": 42,
  "summary": "Se detectaron múltiples intentos fallidos de inicio de sesión SSH...",
  "risk_level": "high",
  "mitre_techniques": ["T1110", "T1110.001"],
  "reasoning": "..."
}
```

`risk_level` ∈ `{low, medium, high, critical}`.

Persistencia: cada llamada crea una fila en `alerts` con `user_id` =
usuario autenticado. El `id` devuelto se usa para `/api/recommend` y
`/api/alerts/{id}`.

Errores:

- `401` sin sesión.
- `422` validación de payload.
- `429` rate-limit.
- `502` AI provider error / AI response could not be processed.

## Next Step Recommender

### `POST /api/recommend`

Auth: requerida. Rate-limited.

Body (uno de los dos modos):

```json
{"alert_id": 42, "model": "gemini-2.5-flash-lite"}
```

```json
{"log": "raw log...", "source": "auth.log"}
```

Validación:

- `alert_id`: ≥1 si presente.
- Si no hay `alert_id`, `log` obligatorio (1..20000, no whitespace).
- `source`: ≤200.
- `model`: opcional, allowlist.

Comportamiento:

- Con `alert_id`: carga la alerta de DB, valida ownership (404 a
  no-owner), usa `summary` y `risk_level` previos como contexto, y
  **persiste la recomendación** ligada a la alerta.
- Con `log` directo: análisis fire-and-forget, **no persiste**.

Respuesta:

```json
{
  "id": 7,
  "alert_id": 42,
  "actions": [
    {
      "title": "Investigar reputación de IP de origen",
      "detail": "Consultar VirusTotal/AbuseIPDB con 91.234.56.78...",
      "rationale": "Verifica si la IP ya está marcada antes de bloquear."
    }
  ],
  "priority": "high",
  "learning_notes": "Brute force responses always start with containment..."
}
```

Si `id` y `alert_id` son `null`, es modo no persistido.

Errores: 401, 404 (alert_id no encontrado o no es tuyo), 422, 429, 502.

## Chat IA + RAG

### `POST /api/chat`

Auth: requerida. Rate-limited.

Body:

```json
{
  "messages": [
    {"role": "user", "content": "¿Qué es T1110 y cómo lo detecto?"}
  ],
  "log_context": "Apr 25 ... Failed password ...",
  "model": "gemini-2.5-flash-lite"
}
```

Validación:

- `messages`: 1..30 elementos.
- `ChatMessage.role`: `"user"` | `"assistant"` | `"system"`.
- `ChatMessage.content`: 1..4000 chars, no whitespace.
- `log_context`: opcional, ≤20000.
- `model`: opcional, allowlist.

Comportamiento:

1. Embeb el último mensaje del usuario.
2. Recupera top-5 docs de Chroma `soc_kb`.
3. Envuelve KB en `BEGIN/END_UNTRUSTED_KB` y `log_context` en
   `BEGIN/END_UNTRUSTED_LOG`.
4. Llama a Gemini chat con el system prompt anti-injection.

Respuesta:

```json
{
  "reply": "MITRE T1110 (Brute Force) ... cite [mitre:T1110]...",
  "sources": ["mitre:T1110", "mitre:T1110.001", "owasp:A07:2025"]
}
```

`sources` son los IDs de los docs recuperados, en el orden devuelto por
Chroma. El frontend los renderiza como pills clicables a
attack.mitre.org / owasp.org.

## Histórico de alertas

### `GET /api/alerts?limit=N&offset=M`

Auth: requerida.

- `limit`: 1..500 (default 50).
- `offset`: ≥0 (default 0).

Filtros automáticos:

- `analyst`: solo sus alertas (`WHERE user_id = current_user.id`).
- `admin`: todas, incluyendo legacy ownerless (Phase 0–3).

Respuesta: array de `AlertSummary`:

```json
[
  {
    "id": 42,
    "source": "auth.log",
    "summary": "...",
    "risk_level": "high",
    "mitre_techniques": ["T1110", "T1110.001"],
    "created_at": "2026-04-27T15:46:39.497Z"
  }
]
```

### `GET /api/alerts/{id}`

Auth: requerida.

Devuelve `AlertDetail` con todas las recomendaciones anidadas. 404 a
no-owner (no leak de existencia).

```json
{
  "id": 42,
  "log": "...",
  "source": "auth.log",
  "summary": "...",
  "risk_level": "high",
  "mitre_techniques": ["T1110"],
  "reasoning": "...",
  "created_at": "...",
  "recommendations": [
    {
      "id": 7,
      "actions": [...],
      "priority": "high",
      "learning_notes": "...",
      "created_at": "..."
    }
  ]
}
```

## Dashboard analítico

### `GET /api/stats`

Agregados sobre las alertas y recomendaciones del scope del usuario.
Analysts ven sólo lo suyo (`scope: "self"`); admins ven todo el sistema
(`scope: "all"`) más conteo de usuarios y un breakdown por usuario.

```json
{
  "scope": "self",
  "totals": {
    "alerts": 12,
    "recommendations": 9,
    "users": null
  },
  "by_risk": [
    {"risk_level": "high", "count": 5},
    {"risk_level": "medium", "count": 4},
    {"risk_level": "low", "count": 3}
  ],
  "top_mitre": [
    {"technique": "T1110", "count": 4},
    {"technique": "T1059", "count": 3}
  ],
  "daily_last_30d": [
    {"day": "2026-05-01", "count": 2},
    {"day": "2026-05-02", "count": 5}
  ],
  "by_user": null
}
```

Notas:

- `daily_last_30d` agrupa por `date_trunc('day', created_at)` y sólo
  devuelve días con al menos una alerta; el frontend rellena los huecos.
- `top_mitre` usa `unnest(mitre_techniques)` (Postgres-only) y limita a 10.
- `by_user` y `totals.users` sólo se pobla cuando `scope == "all"`.

## Administración (RBAC)

Todos los endpoints `/api/admin/*` están gateados por
`require_perm("clave")`. La política por defecto otorga todas las claves
al rol `admin` y ninguna al rol `analyst`, pero un admin puede
modificarla desde la matriz de permisos. Si tu rol no tiene la clave, el
endpoint devuelve `403`.

### `GET /api/admin/users`

Permiso: `users.list`. Devuelve `list[UserMe]` ordenado por `id`.

### `POST /api/admin/users`

Permiso: `users.create`. Body:

```json
{"name": "Alice", "last_name": "Smith", "email": "a@b.com",
 "password": "min8chars", "role": "analyst"}
```

- 201: `UserMe` recién creado. Se audita como `user.create`.
- 409: email duplicado.

### `PUT /api/admin/users/{id}/password`

Permiso: `users.update_password`. Body: `{"new_password": "..."}` (≥8 chars).

Bumpea `password_version` del target → todas sus sesiones JWT existentes
quedan invalidadas en el siguiente request. Auditado como
`user.password_reset`.

### `PUT /api/admin/users/{id}/role`

Permiso: `users.update_role`. Body: `{"role": "admin" | "analyst"}`.

- 400: intentas auto-democirte o democir al último admin.
- 200: `UserMe` actualizado. Bumpea `password_version` → la nueva
  política aplica al siguiente request del target. Auditado como
  `user.role_change` con `details.from`/`details.to`.

### `DELETE /api/admin/users/{id}`

Permiso: `users.delete`.

- 204: borrado. Las alertas del usuario quedan con `user_id = NULL`.
- 400: intentas borrarte a ti mismo o al último admin.
- 404: no existe.

Auditado como `user.delete`.

### `GET /api/admin/audit`

Permiso: `audit.view`. Query string:

| Parámetro | Tipo | Default | Notas |
| --- | --- | --- | --- |
| `limit` | int | 100 | máx 500 |
| `offset` | int | 0 | |
| `action` | str | — | match exacto sobre el verbo (ej. `user.delete`) |
| `actor_email` | str | — | substring case-insensitive |

Respuesta: `list[AuditLogEntry]` ordenada por `created_at DESC`.

```json
{
  "id": 17,
  "created_at": "2026-05-03T18:04:21Z",
  "actor_id": 1,
  "actor_email": "admin@prueba.com",
  "action": "user.role_change",
  "target_type": "user",
  "target_id": 4,
  "target_label": "alice@example.com",
  "details": {"from": "analyst", "to": "admin"},
  "ip": "172.18.0.1"
}
```

### `GET /api/admin/permissions`

Permiso: `permissions.manage`. Devuelve la matriz completa
(`role × permission_key`) con la política efectiva en el momento.

```json
[
  {
    "permission_key": "users.list",
    "area": "Usuarios",
    "action": "Listar usuarios",
    "role": "admin",
    "allowed": true,
    "locked": false,
    "default": true
  }
]
```

### `PUT /api/admin/permissions`

Permiso: `permissions.manage`. Bulk update. Body:

```json
{
  "changes": [
    {"role": "analyst", "permission_key": "audit.view", "allowed": true}
  ]
}
```

- 200: matriz completa actualizada.
- 400: clave no existe o está marcada `locked` (p. ej.
  `permissions.manage` no se puede modificar para evitar lockout).

Cada diff se persiste como una sola fila en `audit_logs` con
`action = "permissions.update"` y `details.changes` con la lista de
celdas modificadas.

### `GET /api/admin/settings`

Permiso: `permissions.manage`. Devuelve el estado actual de los flags
mutables en runtime. Respuesta:

```json
{
  "public_registration_enabled": false
}
```

El valor sale de la tabla `app_settings` si existe la fila, y cae al
`ALLOW_PUBLIC_REGISTRATION` del entorno como fallback cuando todavía no
se ha tocado el toggle desde la UI.

### `PUT /api/admin/settings/public-registration`

Permiso: `permissions.manage`. Abre o cierra el registro público sin
reiniciar la API.

```json
{ "enabled": true }
```

- 200: devuelve `AppSettingsView` actualizado.
- 403: rol sin `permissions.manage`.

Cada cambio se persiste en `app_settings` (clave
`public_registration_enabled`) y se audita con
`action = "settings.public_registration.update"`,
`details = {"from": <bool>, "to": <bool>}`. Si el nuevo valor es igual
al anterior no se escribe fila de auditoría (idempotente).

> El endpoint `/api/auth/register` consulta este flag en cada petición,
> así que el cambio surte efecto inmediatamente para todos los
> contenedores que compartan la BD.

## Errores comunes (resumen)

| Código | Condición |
|--------|-----------|
| `401` | Sin cookie o JWT inválido/expirado/`pv` desfasado |
| `403` | `require_perm` denegado (rol no tiene esa clave) |
| `404` | Recurso no existe **o** no es tuyo (analyst sin permisos) |
| `409` | Conflicto, ej. email duplicado en register / update profile / create admin user |
| `422` | Validación Pydantic |
| `429` | Rate limit excedido |
| `502` | LLM provider error o respuesta inválida |
| `503` | KB / Chroma inalcanzable |

## Prueba rápida con curl

```bash
# Register + login (capturar cookie)
curl -c /tmp/c.txt -X POST http://localhost:8080/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"a@b.com","password":"changeme123"}'

curl -c /tmp/c.txt -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"a@b.com","password":"changeme123"}'

# Endpoint protegido con la cookie
curl -b /tmp/c.txt -X POST http://localhost:8080/api/explain \
  -H "Content-Type: application/json" \
  -d '{"log":"sshd Failed password from 1.2.3.4"}'

# Logout
curl -b /tmp/c.txt -c /tmp/c.txt -X POST http://localhost:8080/api/auth/logout
```

## Ver schemas en Swagger

`http://localhost:8080/docs` muestra todos los schemas Pydantic con
ejemplos. `http://localhost:8080/openapi.json` devuelve la spec OpenAPI
completa para integración con generadores de cliente o herramientas de
testing.


## Integraciones SIEM — Wazuh (Práctica 2)

Detalle completo, ejemplos y códigos de error en
[13-integracion-wazuh.md](13-integracion-wazuh.md#6-endpoints).

| Método | Ruta | Auth |
|---|---|---|
| POST | `/api/integrations/wazuh/webhook` | `Authorization: Bearer <WAZUH_WEBHOOK_TOKEN>` |
| POST | `/api/integrations/wazuh/pull` | sesión + permiso `integrations.manage` |
| GET | `/api/integrations/wazuh/status` | sesión + permiso `integrations.manage` |
| POST | `/api/alerts/{id}/analyze` | sesión (rate limit LLM) |

`GET /api/alerts` acepta ahora `origin=manual|wazuh` y `pending=true|false`,
y cada alerta incluye `origin`, `external_id`, `rule_level`, `agent_name`,
`event_at` y `analyzed_at`.


## Informe de incidente (Práctica 2)

`POST /api/reports/incident` → PDF (`?format=json` para el informe
estructurado). Detalle en [15-informe-incidente.md](15-informe-incidente.md#4-api).

## Idioma de respuesta (Práctica 2)

`/api/explain`, `/api/recommend`, `/api/chat`, `/api/alerts/{id}/analyze`
y `/api/reports/incident` aceptan `language: "es" | "en" | "fr" | "auto"`
y leen `Accept-Language`. `ChatResponse` incluye `language`. Regla en
[16-multiidioma.md](16-multiidioma.md#2-respuestas-de-la-ia--regla-de-decisión).

## MFA / TOTP (Práctica 2)

`POST /api/auth/login` ya no abre sesión si `MFA_REQUIRED=true`: devuelve
`{"user": null, "mfa_required": true, "mfa_setup_required": bool, "expires_at": …}`.

| Método | Ruta | Auth |
|---|---|---|
| POST | `/api/auth/mfa/setup` | cookie `soc_mfa_pending` |
| POST | `/api/auth/mfa/verify` | cookie `soc_mfa_pending` |
| GET | `/api/auth/mfa/status` | sesión |
| POST | `/api/auth/mfa/recovery-codes` | sesión + `{"code"}` |
| POST | `/api/admin/users/{id}/mfa/reset` | `users.reset_mfa` |

Detalle en [17-mfa-totp.md](17-mfa-totp.md).


## Recuperar contraseña

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| POST | `/api/auth/forgot-password` | `{"email"}` | 202 `{"message", "reset_link_dev"}` (siempre el mismo mensaje) |
| POST | `/api/auth/reset-password` | `{"token", "new_password"}` | 204 · 400 enlace inválido/caducado · 422 contraseña débil |

Detalle en [19-recuperar-contrasena.md](19-recuperar-contrasena.md).
