# 14 · Práctica 2 — Plan y estado de las mejoras

Mejoras seleccionadas del Road Map (sección 8 del informe de la Práctica 1),
implementadas **una fase cada vez** con validación del equipo entre fases.

| Fase | Mejora (roadmap) | Prioridad | Estado | Documento |
|---|---|---|---|---|
| 1 | #1 Integración directa con SIEM → **Wazuh** (push + pull) | Alta | ✅ implementada | [13-integracion-wazuh.md](13-integracion-wazuh.md) |
| 2 | #4 Generación automática del informe de incidente (PDF) | Alta | ✅ implementada | [15-informe-incidente.md](15-informe-incidente.md) |
| 3 | #6 Interfaz multiidioma ES/EN con detección automática | Baja | ✅ implementada | [16-multiidioma.md](16-multiidioma.md) |
| 4 | 8.2 Autenticación MFA (TOTP) **obligatoria para todos** | — | ✅ implementada | [17-mfa-totp.md](17-mfa-totp.md) |

> Todas las fases están implementadas y revisadas, pero **la suite
> completa (pytest, `alembic check`, `next build`, Playwright) debe
> ejecutarse en CI o en local antes de desplegar**: el entorno donde se
> desarrollaron no tenía acceso a PyPI/npm. Ver «Checklist de despliegue».

## Decisiones tomadas

| Tema | Decisión | Motivo |
|---|---|---|
| SIEM | Wazuh en lugar de Elastic/Splunk | Open source, ya usado en el máster, trae mapeo MITRE nativo |
| Modo de ingesta | Push (integratord → webhook) **y** pull (Wazuh Indexer) | Push = tiempo real; pull = recuperación si la API estuvo caída |
| Entorno Wazuh | Simulador incluido; no se añade Wazuh al compose | Wazuh single-node necesita ~4 GB RAM extra; no cabe en el CPX22 |
| IA en la ingesta | No automática; botón «Analizar con IA» | Proteger la cuota compartida de Gemini ante tormentas de alertas |
| MFA | Obligatorio para todos los usuarios | Requisito del roadmap 8.2 |
| Informe | IA redacta (JSON), PDF determinista con ReportLab | Evita markup generado por IA; mismo PDF reproducible |
| Idioma | Detecta el idioma del analista; si no, el de la interfaz | Los logs no sirven para detectar (inglés técnico) |
| QR del MFA | Generado en el servidor con ReportLab (SVG) | Sin dependencia extra ni servicios externos con el secreto |

## Cambios por fase

### Fase 1 — Wazuh

Backend
- `app/config.py`: variables `WAZUH_*` + validación en producción.
- `app/models.py`: `AlertOrigin` y columnas SIEM en `Alert`.
- `alembic/versions/20261005_1200_wazuh_integration.py`: migración `0005`.
- `app/services/wazuh.py` (nuevo): normalización, ingesta deduplicada, pull del indexer, estado, poller.
- `app/services/alert_access.py` (nuevo): reglas de visibilidad compartidas.
- `app/routers/integrations.py` (nuevo): webhook, pull, status.
- `app/routers/alerts.py`: filtros `origin`/`pending` + `POST /alerts/{id}/analyze`.
- `app/routers/recommend.py`: usa `can_view_alert` (analistas pueden recomendar sobre la cola Wazuh).
- `app/routers/explain.py`: rellena `analyzed_at`.
- `app/services/permissions.py`: permiso `integrations.manage`.
- `app/main.py`: router + poller opcional en `lifespan`.

Frontend
- `src/app/siem/page.tsx` (nuevo): cola de triage, filtros, auto-refresco, panel admin.
- `src/lib/api.ts`: tipos SIEM, `listAlerts` con filtros, `analyzeStoredAlert`, `getWazuhStatus`, `wazuhPullNow`.
- `src/components/AppShell.tsx`: entrada de menú «SIEM · Wazuh».
- `src/lib/i18n.tsx`: textos ES/EN/FR.

Wazuh / herramientas
- `integrations/wazuh/custom-soccopilot.py`, `ossec-integration.xml`, `wazuh_simulator.py`.

Tests / CI
- `tests/test_wazuh.py`, `tests/test_e2e_wazuh.py`; `.github/workflows/e2e.yml` ejecuta el nuevo e2e.

### Fase 2 — Informe de incidente (PDF)

- `app/services/incident_report.py`, `app/schemas/reports.py`, `app/routers/reports.py` (nuevos).
- `requirements.txt`: `reportlab==4.2.5`; `Dockerfile`: `fonts-dejavu-core`.
- Frontend: `components/IncidentReportButton.tsx` (nuevo), botón en `chat` y `respond`, `downloadIncidentReport` en `lib/api.ts`.
- Tests: `tests/test_incident_report.py`. Ejemplo: `docs/assets/ejemplo-informe-incidente.pdf`.

### Fase 3 — Multiidioma ES/EN

- `app/services/language.py` (nuevo); parámetro `language` en explainer / recommender / chat; routers resuelven idioma.
- `main.py`: `Accept-Language` en CORS.
- Frontend: cabecera `Accept-Language` en todas las peticiones, autodetección del idioma del navegador, sugerencias del chat traducidas.
- Tests: `tests/test_language.py`.

### Fase 4 — MFA TOTP obligatorio

- `app/services/mfa.py`, `app/routers/mfa.py` (nuevos); migración `0006_mfa_totp`.
- `app/services/auth.py` (claim `mfa`, token `mfa_pending`), `app/middleware/auth.py` (exige `mfa`), `app/routers/auth.py` (login en dos pasos), `app/routers/admin.py` (reset MFA), permiso `users.reset_mfa`, `config.py` (`MFA_*`, bloqueo en producción).
- Frontend: `components/MfaStep.tsx` (nuevo), login en dos pasos, sección MFA en perfil, botón «Reset MFA» en admin.
- Tests: `tests/test_mfa.py`, `tests/test_e2e_mfa.py`; CI e2e con `MFA_REQUIRED=false` para los tests antiguos.

### Extra — Paleta de colores

- `tailwind.config.ts` (colores por variables CSS), `src/app/globals.css` (valores por tema, sin `!important`), botones sólidos y campos en `alerts`, `chat`, `siem`, `respond`, `login`, `profile`, `settings/llm`, `admin`, `verify`, `MfaStep`, `IncidentReportButton`, `AppShell`; gráficas en `dashboard`. Detalle en [18-paleta-colores.md](18-paleta-colores.md).

### Extra — Recuperar contraseña

- Endpoints `/api/auth/forgot-password` y `/api/auth/reset-password`, migración `0007_password_reset`, páginas `/forgot-password` y `/reset-password`, enlace en el login. Detalle en [19-recuperar-contrasena.md](19-recuperar-contrasena.md).

## Checklist de despliegue

1. `.env`: definir `APP_ENCRYPTION_KEY` (obligatoria para MFA), `MFA_REQUIRED=true`, y si se usa Wazuh `WAZUH_WEBHOOK_TOKEN` / `WAZUH_INDEXER_*`.
2. Reconstruir la imagen de la API (nueva dependencia `reportlab` y fuentes): `docker compose ... up -d --build api`.
3. Migraciones `0005` y `0006` se aplican solas al arrancar (`init_db`); comprobar con `alembic current`.
4. Avisar al equipo: **todos** tendrán que escanear el QR en su próximo login. El admin debe enrolarse primero.
5. Ejecutar: `ruff check apps/api`, `pytest`, `RUN_E2E=1 pytest tests/test_e2e*.py`, `alembic check`, `npm run lint && npm run build`.
