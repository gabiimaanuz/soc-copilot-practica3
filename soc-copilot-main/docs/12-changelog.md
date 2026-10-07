# Changelog de UI/UX

## [05/10/2026] - «¿Has olvidado tu contraseña?»

Nuevo enlace en el inicio de sesión. Envía por email un enlace de un solo
uso (30 min) para elegir una contraseña nueva, sin tener que crear otra
cuenta. Ver [19-recuperar-contrasena.md](19-recuperar-contrasena.md).

## [05/10/2026] - Nueva paleta de colores (oscuro y claro)

Todos los textos, insignias de nivel/riesgo, estados y botones se leen bien
en los dos temas (contraste WCAG AA). En modo claro desaparecen los
amarillos y cian pálidos sobre blanco; en oscuro los bordes y textos
secundarios se distinguen mejor. Ver [18-paleta-colores.md](18-paleta-colores.md).

## [05/10/2026] - Práctica 2 · Fase 4: MFA (TOTP) obligatorio

El inicio de sesión pasa a tener dos pasos para **todos** los usuarios:
contraseña + código de 6 dígitos de una app de autenticación. En el
primer login se muestra un QR y 10 códigos de recuperación. El perfil
muestra el estado del MFA y permite regenerar códigos; los admins tienen
«Reset MFA» por usuario. Ver [17-mfa-totp.md](17-mfa-totp.md).

## [05/10/2026] - Práctica 2 · Fase 3: respuestas ES/EN con detección automática

La IA responde en el idioma en que escribe el analista (o, si no se puede
detectar, en el de la interfaz). La interfaz detecta el idioma del
navegador en la primera visita. Ver [16-multiidioma.md](16-multiidioma.md).

## [05/10/2026] - Práctica 2 · Fase 2: informe de incidente en PDF

Botón «Generar informe de incidente (PDF)» en el Chat IA y en la página de
respuesta de cada alerta. Ver [15-informe-incidente.md](15-informe-incidente.md).

## [05/10/2026] - Práctica 2 · Fase 1: integración con Wazuh

Nueva página **SIEM · Wazuh** (`/siem`): las alertas de Wazuh llegan solas
(webhook de integratord o pull del Wazuh Indexer) a una cola de triage
compartida, priorizada por nivel de regla y con MITRE precargado. Botón
«Analizar con IA» por alerta; los admins ven el estado de la integración
y pueden «Sincronizar ahora». Detalle técnico en
[13-integracion-wazuh.md](13-integracion-wazuh.md) y lista de archivos en
[14-practica2.md](14-practica2.md).

## [18/05/2026] - Toggle de registro público desde el panel admin

Los admins pueden ahora abrir o cerrar el registro de cuentas
directamente desde `/admin → Usuarios`, sin tocar el `.env` ni reiniciar
contenedores. El cambio surte efecto inmediatamente y queda en auditoría.

**Archivos modificados:**
- `apps/api/alembic/versions/20260518_2200_app_settings.py` (nuevo):
  migración 0004 que crea la tabla `app_settings(key, value, updated_at,
  updated_by)` para guardar flags mutables en runtime.
- `apps/api/app/models.py`: nuevo modelo `AppSetting`.
- `apps/api/app/services/settings.py` (nuevo): encapsula la lógica de
  override DB → fallback env. Función `is_public_registration_enabled(db)`
  es ahora la fuente única de verdad.
- `apps/api/app/routers/auth.py`: `/auth/register` consulta el servicio
  en lugar del `settings.allow_public_registration` directo.
- `apps/api/app/routers/admin.py`: `GET /api/admin/settings` y
  `PUT /api/admin/settings/public-registration`, gated por
  `permissions.manage` y con audit log
  `settings.public_registration.update`.
- `apps/api/app/schemas/admin.py`: `AppSettingsView` y
  `UpdatePublicRegistrationRequest`.
- `apps/web/src/lib/api.ts`: helpers `getAppSettings()` y
  `setPublicRegistrationEnabled()`.
- `apps/web/src/app/admin/page.tsx`: banner en el tab Usuarios con
  estado (Abierto / Cerrado) y botón con la copy correcta para el
  siguiente estado.
- `docs/operations.md`: la sección 4 documenta las 3 vías (UI, sed sobre
  `.env`, INSERT en `app_settings`) y explica la precedencia DB > env.
- `docs/10-manual-usuario.md`: nueva sección "Abrir el registro
  temporalmente para una demo" y entrada en la tabla de admin features.

**Impacto.** Demos al tribunal y pruebas con compañeros ya no requieren
SSH al servidor. El flag por defecto sigue siendo lo que diga
`ALLOW_PUBLIC_REGISTRATION` del `.env`; el override en BD solo aparece
cuando alguien toca el toggle.

## [18/05/2026] - Verificación por email vía SMTP (Gmail)

Cableado completo del flujo de verificación. Hasta hoy el endpoint
generaba el token pero nunca enviaba el correo: el link salía en la
respuesta JSON (modo dev) o se perdía silenciosamente (producción).

**Archivos modificados:**
- `apps/api/app/services/email.py` (nuevo): envío SMTP con stdlib
  `smtplib`, plantilla HTML+texto, soporte STARTTLS y SSL, timeout
  configurable. Fallo silencioso con log (`email.send_failed`) — un SMTP
  caído nunca rompe el registro.
- `apps/api/app/config.py`: añadidas 8 variables (`SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`,
  `SMTP_USE_STARTTLS`, `SMTP_USE_SSL`, `SMTP_TIMEOUT_SECONDS`).
- `apps/api/app/routers/auth.py`: el `/auth/register` llama a
  `send_verification_email`. El fallback de link en la respuesta solo
  se activa si SMTP no está configurado **y** no estamos en producción.
- `apps/web/src/app/login/page.tsx`: distingue 403 de
  `/auth/register` (registro cerrado) vs 403 de `/auth/login` (email no
  verificado) con mensajes específicos.

**Producción.** El servidor envía vía `smtp.gmail.com:587` con un App
Password de Google (no la contraseña real de la cuenta). 2FA debe estar
activado en la cuenta para poder generar App Passwords.

## [18/05/2026] - Despliegue en producción (Hetzner CPX22)

Infraestructura puesta en marcha en un VPS Hetzner CPX22 (Nuremberg) con
todo el stack containerizado detrás de Caddy 2 + Let's Encrypt.

**Highlights:**
- URL pública: <https://soc-copilot.duckdns.org>
- Hardening SSH: clave-only, root deshabilitado, `AllowUsers soc`,
  3 intentos máximos, UFW (22/80/443) + fail2ban activos.
- Stack Docker: Postgres 16 + ChromaDB + FastAPI + Next.js + Caddy con
  HTTP/3.
- Backups Postgres diarios (cron) con retención 14 días + tarea
  programada en Windows que descarga los dumps a `Documents/` con
  retención 30 días.
- KB cargada en Chroma: 697 técnicas MITRE ATT&CK Enterprise + 10
  entradas OWASP Top 10 2025 = 707 docs.
- Verificación de salud completa documentada en `docs/operations.md` con
  pre-flight checklist, troubleshooting típico (migraciones pendientes,
  text/plain 500, conflictos de `git pull` por patches manuales) y
  recipe `TestClient` para tracebacks ASGI.

**Archivos creados/modificados:**
- `apps/web/Dockerfile`: stage `builder` acepta `ARG NEXT_PUBLIC_API_URL`
  para que la URL pública quede embebida en el bundle de Next.
- `infra/docker-compose.prod.example.yml`: forward del build-arg vía
  `args:`. Indentación del bloque `web:` corregida (era 4 espacios en
  lugar de 2).
- `scripts/deploy.sh`: `git pull` + validación de secretos en `.env` +
  `up -d --build` + status.
- `docs/operations.md`: runbook completo en español.

## [17/05/2026] - Política de contraseñas unificada en reseteo admin

El modal "Resetear contraseña" del panel `/admin → Usuarios` ahora aplica
exactamente la misma política que el registro de cuenta: mínimo 10
caracteres, mayúscula, minúscula, dígito, símbolo, puntuación zxcvbn ≥ 2
y campo de confirmación con verificación de coincidencia en vivo. El
botón Guardar queda deshabilitado hasta que se cumplen todos los
criterios. Se extrajo la política a un módulo compartido para evitar
divergencia entre flujos.

**Archivos modificados:**
- `apps/web/src/lib/password.ts` (nuevo): reglas, loader perezoso de
  zxcvbn-ts, constantes de fortaleza, helper `evaluatePassword`.
- `apps/web/src/app/login/page.tsx`: refactor para consumir el módulo
  compartido (sin cambios funcionales).
- `apps/web/src/app/admin/page.tsx`: el modal `pwUser` añade campo
  Confirmar contraseña, barra de fortaleza, checklist de reglas y
  validación de submit; el título pasa a "Resetear contraseña".
- `apps/api/app/schemas/admin.py`: `ChangePasswordRequest` y
  `CreateUserRequest` pasan de `min_length=8` a `min_length=MIN_LENGTH`
  (10) y aplican el validador `check_password` (mismas reglas que
  `RegisterRequest`). Cierra el bypass por llamada directa a la API.
- `docs/security.md`: tabla de validación de schemas refleja la nueva
  política en los 3 endpoints (register, admin reset, admin create).

**Impacto:**
- Un admin ya no puede establecer contraseñas débiles (≥ 8 caracteres
  sin clases ni fortaleza mínima) al resetear cuentas ajenas, ni vía UI
  ni vía API directa.
- Tras un reseteo exitoso, las sesiones activas del usuario afectado se
  invalidan automáticamente (comportamiento ya existente).

## [17/05/2026] - Confirmación inline para eliminar usuario

El botón **Eliminar** de la tabla de usuarios en `/admin` ya no usa
`window.confirm()`. Pasa a una confirmación inline ¿Eliminar? Sí / No
con el mismo patrón visual que la confirmación de "Resetear cuota"
(botones emerald/slate, texto rose para la pregunta).

**Archivos modificados:**
- `apps/web/src/app/admin/page.tsx`: nuevo estado `confirmDeleteId`,
  `handleDelete` ya no abre el diálogo nativo, render condicional del
  botón rojo o de los botones Sí/No.

**Impacto:**
- UX consistente con el resto de acciones críticas del panel.
- Sin dependencia del prompt nativo del navegador (mejor accesibilidad
  y testeabilidad).

## [17/05/2026] - Acciones del panel de usuarios como botones

Las acciones de cada fila en `/admin → Usuarios` (Resetear cuota,
Password, Eliminar) pasan de enlaces subrayados a botones con borde,
fondo translúcido y estado hover/disabled. La acción "Password" se
renombra a **"Resetear contraseña"**. Layout flex con `gap-2 flex-wrap`
para pantallas estrechas.

**Archivos modificados:**
- `apps/web/src/app/admin/page.tsx`: estilos de la celda de acciones,
  texto del botón.

**Impacto:**
- Visualmente más reconocibles como controles interactivos.
- Etiqueta más explícita sobre lo que hace la acción.

## [17/05/2026] - Migración OWASP Top 10 2021 → 2025

Se actualiza el dataset RAG y todas las referencias de la app a la
edición 2025 del OWASP Top 10 (publicada en 2025). Cambios estructurales
respecto a 2021:

- A01 absorbe SSRF (antes A10).
- A02 Security Misconfiguration sube de #5 a #2.
- A03 Software Supply Chain Failures (nueva, reemplaza/amplía la antigua
  A06 Vulnerable & Outdated Components).
- A07 renombrada a "Authentication Failures".
- A09 renombrada a "Security Logging & Alerting Failures".
- A10 Mishandling of Exceptional Conditions (nueva).

**Archivos modificados:**
- `apps/api/scripts/owasp_top10.py`: dataset reescrito con `A##:2025`,
  descripciones curadas y tags. Alias `OWASP_TOP_10_2021 =
  OWASP_TOP_10_2025` para compatibilidad temporal.
- `apps/api/scripts/ingest_kb.py`: imports y logs apuntan a la lista
  2025.
- `apps/api/app/services/chat.py`: el system prompt cita `A##:2025`.
- `apps/api/tests/test_smoke.py`: fixtures de OWASP migrados.
- `apps/web/src/app/chat/page.tsx`: starter prompt y URL externa.
- Docs: `README.md`, `01-instalacion-local.md`, `02-estado-fases.md`,
  `03-arquitectura.md`, `06-api-reference.md`, `08-rag-ingestion.md`,
  `09-diagramas.md`, `10-manual-usuario.md`.

**Operación post-deploy:**
Re-ingerir la KB con `docker compose exec api python -m
scripts.ingest_kb --force` para sustituir los 10 docs `owasp:A##:2021`
por `owasp:A##:2025` en Chroma. Tras la migración la colección queda
con ~707 docs (691 MITRE + 10 OWASP 2025 + posibles extras).

**Impacto:**
- Las citas del chat usan IDs `owasp:A##:2025`.
- Las pills clicables en `/chat` enlazan a la sección 2025 de
  `owasp.org/Top10/`.

## [17/05/2026] - Ocultamiento de Next Step Recommender

Se ha procedido a ocultar la opción "Next Step Recommender" de las interfaces principales por solicitud del usuario.

**Archivos modificados:**
- `apps/web/src/app/page.tsx`: Se eliminó el objeto correspondiente a `/respond` del array de tiles `TILES`.
- `apps/web/src/components/AppShell.tsx`: Se eliminó el objeto correspondiente a `/respond` del menú lateral `OPS_NAV`.

**Impacto:**
- Los usuarios ya no verán el enlace a `/respond` en la página principal ni en la barra de navegación lateral.
- La ruta `/respond` y el componente de la página (`apps/web/src/app/respond/page.tsx`) aún existen en el código y pueden ser accedidos directamente por URL o desde otros lugares que conserven el enlace (como el botón "Next Step Recommender" en los detalles de una alerta, el cual no fue solicitado a remover en esta iteración).

## [17/05/2026] - Ocultamiento de textos de rutas

Se ha procedido a ocultar todos los textos en la interfaz que hacian mencion explicita a las rutas de las paginas (ej. /alerts, /admin).

**Archivos modificados:**
- `apps/web/src/app/page.tsx`: Se eliminaron los bloques de texto que mostraban `t.hint` y `/admin` en las tarjetas de la pagina principal.

## [17/05/2026] - Reemplazo de ruta en historico

Se reemplazó la mencion explícita de la ruta `/alerts` por el nombre del menú `Alertas` en la vista del historial de alertas, mejorando la legibilidad para los usuarios finales.

**Archivos modificados:**
- `apps/web/src/app/history/page.tsx`: Modificado el estado vacío para que el enlace diga "Alertas" en lugar de "/alerts".

## [17/05/2026] - Estilizado de enlaces a botones

Se convirtieron los enlaces de texto plano que navegaban entre los módulos de Alertas y Chat hacia el Historial y viceversa, dándoles la apariencia de botones secundarios interactivos para mejorar la consistencia visual y la accesibilidad.

**Archivos modificados:**
- `apps/web/src/app/alerts/page.tsx`: El enlace a `/history` ahora tiene clases de botón.
- `apps/web/src/app/chat/page.tsx`: El enlace a `/alerts` ahora tiene clases de botón y el texto capitalizado.

## [17/05/2026] - Ajuste de estilos de botones de navegacion

Se unificó el estilo visual de los nuevos botones añadidos en los módulos de Alertas y Chat, aplicando las mismas clases CSS usadas por el botón secundario del Dashboard (`Analizar una alerta`) para asegurar total consistencia en el sistema de diseño.

**Archivos modificados:**
- `apps/web/src/app/alerts/page.tsx`: Clases CSS de botón actualizadas a formato unificado.
- `apps/web/src/app/chat/page.tsx`: Clases CSS de botón actualizadas a formato unificado.

## [17/05/2026] - Reemplazo de texto en estado vacio de Dashboard

Se eliminó la mención explícita a la ruta `/alerts` en el mensaje que aparece cuando el Dashboard no tiene datos, en favor de un texto más descriptivo que invita al usuario a crear su primera alerta, manteniendo la navegación mediante un hipervínculo en el propio texto.

**Archivos modificados:**
- `apps/web/src/app/dashboard/page.tsx`: Modificado el componente de texto del estado vacío.

## [17/05/2026] - Eliminacion de hipervinculo en Dashboard

Se retiró el hipervínculo del mensaje de estado vacío en el Dashboard para que sea únicamente texto plano, siguiendo las preferencias de diseño indicadas.

**Archivos modificados:**
- `apps/web/src/app/dashboard/page.tsx`: El componente <Link> fue removido dejando solo la etiqueta <p>.
