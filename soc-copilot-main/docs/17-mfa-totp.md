# 17 · Autenticación MFA (TOTP) obligatoria — Práctica 2, mejora 8.2

> Roadmap 8.2 «Autenticación MFA: segundo factor obligatorio (TOTP) para
> acceso al panel». Decisión: **obligatorio para todos** los usuarios.
> Estado: implementada. Ver [14-practica2.md](14-practica2.md).

## 1. Flujo

```text
email + contraseña ─► POST /api/auth/login
                       └─ OK → NO hay sesión todavía.
                          Cookie httpOnly soc_mfa_pending (5 min, path /api/auth/mfa)
                          { mfa_required: true, mfa_setup_required: true|false, user: null }

¿primera vez?  sí ─► POST /api/auth/mfa/setup  → QR (SVG) + clave manual
                     POST /api/auth/mfa/verify {code}
                       └─ activa MFA, devuelve 10 códigos de recuperación (una sola vez)
               no ─► POST /api/auth/mfa/verify {code | recovery_code}

verify OK ─► cookie de sesión soc_session con claim "mfa": true
```

- **Usuarios existentes**: sus sesiones anteriores dejan de valer (no
  tienen `mfa: true`) y en el siguiente login se les pide enrolarse.
- Apps compatibles: Google Authenticator, Microsoft Authenticator, Authy,
  FreeOTP, 1Password, Bitwarden… (TOTP estándar, SHA1, 6 dígitos, 30 s).
- **Móvil perdido**: código de recuperación, o un admin pulsa
  **Reset MFA** en `/admin → Usuarios` (permiso `users.reset_mfa`). Eso
  borra el enrolamiento y cierra todas sus sesiones (`password_version`+1).
- **Perfil** (`/profile`): estado del MFA, códigos restantes y generación
  de 10 códigos nuevos (pide un código TOTP).

## 2. Seguridad

| Control | Implementación |
|---|---|
| TOTP RFC 6238 | `services/mfa.py`, librería estándar; validado con los vectores oficiales del RFC |
| Secreto cifrado | Fernet con `APP_ENCRYPTION_KEY` (igual que las BYO keys de Gemini) |
| Anti-replay | se guarda el último *time-step* aceptado; un código no vale dos veces |
| Deriva de reloj | ventana ±1 paso (±30 s) |
| Fuerza bruta | rate limit estricto de auth (5/min/IP) + los fallos de código cuentan para el mismo bloqueo que la contraseña (4 fallos → 15 min) |
| Token intermedio | JWT con `purpose: mfa_pending`, 5 min, cookie httpOnly limitada a `/api/auth/mfa`; `get_current_user` rechaza cualquier token con `purpose` |
| Sin fuga de datos | el login con contraseña correcta **no devuelve** el usuario hasta superar el MFA |
| Códigos de recuperación | 10 × ~49 bits, guardados como SHA-256, de un solo uso |
| QR | generado en el servidor (SVG, ReportLab); el secreto nunca va a un servicio de QR externo |
| Producción | la API **no arranca** con `MFA_REQUIRED=false` en `APP_ENV=production` |
| Auditoría | `auth.login_password_ok`, `auth.mfa_setup_started`, `auth.mfa_enabled`, `auth.mfa_failed`, `auth.login` (con `mfa_method`), `auth.mfa_recovery_regenerated`, `user.mfa_reset` |

## 3. Configuración

```dotenv
MFA_REQUIRED=true          # obligatorio; false solo en suites de test
MFA_ISSUER=SOC Copilot     # nombre que aparece en la app del móvil
APP_ENCRYPTION_KEY=...     # IMPRESCINDIBLE: sin ella /mfa/setup devuelve 503
```

Generar la clave: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
⚠️ Si se cambia `APP_ENCRYPTION_KEY`, los secretos TOTP dejan de poder
leerse y hay que resetear el MFA de los usuarios desde admin.

## 4. API

| Método | Ruta | Auth |
|---|---|---|
| POST | `/api/auth/login` | — (devuelve `mfa_required`) |
| POST | `/api/auth/mfa/setup` | cookie `soc_mfa_pending` |
| POST | `/api/auth/mfa/verify` | cookie `soc_mfa_pending` |
| GET | `/api/auth/mfa/status` | sesión |
| POST | `/api/auth/mfa/recovery-codes` | sesión + código TOTP |
| POST | `/api/admin/users/{id}/mfa/reset` | sesión + `users.reset_mfa` |

## 5. Base de datos

Migración `0006_mfa_totp` en `users`: `mfa_enabled`, `mfa_secret_ciphertext`,
`mfa_enabled_at`, `mfa_last_used_step`, `mfa_recovery_codes` (JSONB).

## 6. Tests

- `tests/test_mfa.py` (offline): vectores RFC 6238, ventana y replay,
  códigos de recuperación, URI/QR, token pendiente rechazado como sesión,
  sesión sin `mfa` rechazada, producción rechaza `MFA_REQUIRED=false`.
- `tests/test_e2e_mfa.py` (Postgres): enrolamiento completo, código
  erróneo, segundo login, código de recuperación de un solo uso, reset por
  admin con cierre de sesiones.
- El resto de e2e (API y Playwright) corre con `MFA_REQUIRED=false` porque
  inician sesión solo con contraseña.
