# Documentacion del proyecto SOC Copilot

Este paquete contiene el estado del proyecto tras el **despliegue en
producción** (fase 5) y refleja el sistema funcionando en
<https://soc-copilot.duckdns.org>. Cubre instalación local para
desarrollo, operación del entorno productivo en Hetzner, y todo lo
necesario para que cualquier miembro del equipo y cualquier evaluador
externo pueda ejecutarlo, mantenerlo o auditarlo.

## Orden recomendado de lectura

| # | Documento | Para qué |
|---|-----------|----------|
| 01 | [Instalacion local](01-instalacion-local.md) | Levantar el stack desde cero en Windows/macOS/Linux |
| 02 | [Estado del proyecto y fases](02-estado-fases.md) | Qué está hecho y qué viene |
| 03 | [Arquitectura tecnica](03-arquitectura.md) | Cómo encajan backend, frontend, DB y Chroma |
| 04 | [Guia de trabajo del equipo](04-guia-equipo.md) | Convenciones, reparto de tareas, validación pre-entrega |
| 05 | [Solucion de problemas](05-solucion-problemas.md) | Errores comunes y cómo desbloquearlos |
| 06 | [Referencia de API](06-api-reference.md) | Todos los endpoints, schemas, auth y rate limit |
| 07 | [Tests y CI](07-testing.md) | Suites unit / E2E, fixtures, GitHub Actions |
| 08 | [Ingesta RAG (Chroma + MITRE + OWASP)](08-rag-ingestion.md) | Cómo poblar y mantener la base de conocimiento |
| 09 | [Diagramas del sistema](09-diagramas.md) | ER, despliegue, secuencia (login/explain/chat/reset/logs), casos de uso, ciclo de vida, pipeline KB, resolución RBAC |
| 10 | [Manual de usuario](10-manual-usuario.md) | Guía para analista/admin: módulos, flujo de trabajo, cuotas, troubleshooting |
| 11 | [Módulo de Auditoría](11-modulo-auditoria.md) | Detalles técnicos y funcionamiento del registro de eventos inmutable |
| 12 | [Changelog de UI/UX](12-changelog.md) | Historial de cambios visibles para el usuario |
| 13 | [Integración con Wazuh (SIEM)](13-integracion-wazuh.md) | Práctica 2 · ingesta push/pull de alertas Wazuh, simulador, seguridad |
| 14 | [Práctica 2 — plan y estado](14-practica2.md) | Mejoras del roadmap seleccionadas, decisiones, cambios por fase y checklist de despliegue |
| 15 | [Informe de incidente en PDF](15-informe-incidente.md) | Práctica 2 · generación del informe desde el chat o la alerta |
| 16 | [Multiidioma ES/EN](16-multiidioma.md) | Práctica 2 · detección automática del idioma de respuesta |
| 17 | [MFA TOTP obligatorio](17-mfa-totp.md) | Práctica 2 · segundo factor, recuperación, reset por admin |
| 18 | [Paleta de colores](18-paleta-colores.md) | Modo oscuro y claro legibles (WCAG AA), cómo cambiar colores |
| 19 | [¿Has olvidado tu contraseña?](19-recuperar-contrasena.md) | Recuperación de contraseña por email, seguridad del enlace |
| —  | [**Operations runbook**](operations.md) | **Operación del entorno productivo en Hetzner**: acceso, deploy, migraciones, backups, troubleshooting |
| —  | [Estado de seguridad y mitigaciones](security.md) | Threats activas y residuales |
| —  | [Reporte de Vulnerabilidades](vulnerability_report.md) | Informe de la auditoría y parches de remediación |
| —  | [Roadmap](roadmap.md) | Plan por fases hasta entrega 25-mayo-2026 |

## Resumen rapido

SOC Copilot es una aplicacion para analistas SOC junior. El backend FastAPI
analiza alertas con Gemini, persiste resultados en PostgreSQL, indexa MITRE
ATT&CK y OWASP Top 10 en ChromaDB para RAG, y expone una API protegida con
JWT en cookie httpOnly invalidable por `password_version`. El frontend
Next.js sirve dashboard, explainer, recommender, analizador de logs con
filtros (IP/puerto/MAC/protocolo/tiempo), histórico, chat con citas, panel
de administración (usuarios, roles, matriz de permisos editable, auditoría)
y página de perfil de usuario.

**Despliegue productivo** en VPS Hetzner CPX22 (Nuremberg) con TLS
automático (Caddy + Let's Encrypt), backups Postgres diarios duplicados
(server + local Windows), verificación de email vía SMTP Gmail, y toggle
admin para abrir/cerrar el registro público sin redeploy.

Fases 0–4 y 4.5 (Dashboard) cerradas + ciclo de hardening admin + **fase
5 (despliegue Hetzner) cerrada**. Fase 6 (informe + demo) en curso de
cara a entrega del 25-mayo-2026.
