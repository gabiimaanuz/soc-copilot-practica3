# SOC Copilot

> IA Copilot para Analistas SOC Junior — Práctica 1 del Máster de
> Ciberseguridad e IA (entrega 25-mayo-2026).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20Next.js%20%2B%20Postgres%20%2B%20ChromaDB-blue)
![Estado](https://img.shields.io/badge/estado-en%20producci%C3%B3n-success)

**Producción:** <https://soc-copilot.duckdns.org>

SOC Copilot es un asistente con IA pensado para apoyar a analistas SOC
junior durante la triage de alertas. Combina cuatro capacidades:

1. **Alert Explainer** — pega un log y obtén resumen, severidad,
   técnica MITRE ATT&CK probable y siguientes pasos.
2. **Next Step Recommender** — recomendaciones accionables sobre una
   alerta ya analizada, con modo aprendizaje opcional.
3. **Chat IA con RAG** — conversación con citas verificables sobre
   MITRE ATT&CK Enterprise y OWASP Top 10 2025 (707 docs en ChromaDB).
4. **Dashboard + panel admin** — KPIs, distribución por riesgo, gestión
   de usuarios, RBAC dinámico, auditoría inmutable.

La IA **no sustituye** al analista: propone hipótesis y referencias. La
decisión final siempre es humana.

---

## Arquitectura en una imagen

```text
                    ┌─────────────────┐
                    │     Caddy 2     │  TLS auto (Let's Encrypt)
                    │  HTTP/2 + HTTP/3│  HSTS preload
                    └────────┬────────┘
                ┌────────────┼────────────┐
                │            │            │
        /api/* │            │            │ /*
                ▼            ▼            ▼
       ┌─────────────┐                 ┌─────────────┐
       │  FastAPI    │◄────────────────│  Next.js    │
       │  (uvicorn)  │   internal API  │  (standalone│
       │             │                 │   runtime)  │
       └──┬───┬───┬──┘                 └─────────────┘
          │   │   │
          │   │   └─── ChromaDB (RAG: MITRE + OWASP)
          │   └─────── Gemini API (chat + embeddings)
          └─────────── Postgres 16 (users, alerts, audit, app_settings)
```

Detalle en [docs/03-arquitectura.md](docs/03-arquitectura.md) y diagramas
Mermaid en [docs/09-diagramas.md](docs/09-diagramas.md).

---

## Quickstart — desarrollo local

Prerrequisitos: Docker Desktop, una API key de Gemini
(<https://aistudio.google.com/app/apikey>), Node 22+ (opcional para
debugging directo).

```bash
git clone git@github.com:f3l0X/soc-copilot.git
cd soc-copilot
cp .env.example .env
# Edita .env y rellena GEMINI_API_KEY + secretos
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

Abre <http://localhost:13500>. El primer usuario que se registre se
convierte automáticamente en `admin`.

Guía completa: [docs/01-instalacion-local.md](docs/01-instalacion-local.md).

### Ingesta de la base de conocimiento

Para que el chat con RAG funcione hay que poblar ChromaDB (~5 min, usa
cuota de Gemini para embeddings):

```bash
docker compose -f infra/docker-compose.yml --env-file .env \
  exec api python -m scripts.ingest_kb
```

Detalle en [docs/08-rag-ingestion.md](docs/08-rag-ingestion.md).

---

## Documentación

| Para… | Lee |
|-------|-----|
| Entender qué hace el sistema | [docs/10-manual-usuario.md](docs/10-manual-usuario.md) |
| Levantar el stack en tu máquina | [docs/01-instalacion-local.md](docs/01-instalacion-local.md) |
| Saber cómo se descompone el código | [docs/03-arquitectura.md](docs/03-arquitectura.md) |
| Operar el entorno de producción | [docs/operations.md](docs/operations.md) |
| Consultar la API | [docs/06-api-reference.md](docs/06-api-reference.md) |
| Ver el estado de cada fase | [docs/02-estado-fases.md](docs/02-estado-fases.md) |
| Auditar la seguridad | [docs/security.md](docs/security.md), [docs/vulnerability_report.md](docs/vulnerability_report.md) |
| Histórico de cambios visibles | [docs/12-changelog.md](docs/12-changelog.md) |

Índice maestro: [docs/00-indice.md](docs/00-indice.md).

---

## Stack técnico

| Capa | Tecnología | Versión |
|------|------------|---------|
| Backend API | FastAPI + Uvicorn | 0.115 / 0.32 |
| ORM + migraciones | SQLAlchemy + Alembic | 2.0 / 1.14 |
| Base de datos | PostgreSQL | 16-alpine |
| RAG / vector store | ChromaDB | 0.5.23 |
| LLM | Gemini (`gemini-2.5-flash-lite`, `gemini-2.5-flash`, embeddings) | API v1 |
| Auth | PyJWT cookie httpOnly + bcrypt + lockout | — |
| Frontend | Next.js (app router, standalone build) | 22-alpine |
| UI | React + Tailwind + Recharts | — |
| Reverse proxy | Caddy 2 | alpine |
| Hosting | Hetzner Cloud CPX22 | Nuremberg |

---

## Estado del proyecto

| Fase | Descripción | Estado |
|------|-------------|--------|
| 1 | Alert Explainer (Gemini + MITRE) | ✅ |
| 2 | Next Step Recommender + persistencia Postgres | ✅ |
| 3 | RAG + Chat IA (MITRE + OWASP en Chroma) | ✅ |
| 4 | Auth + RBAC + tests E2E | ✅ |
| 4.5 | Dashboard analítico | ✅ |
| 5 | Despliegue Hetzner + dominio + HTTPS + backups + SMTP + toggle registro | ✅ |
| 6 | Informe PDF + presentación 10 min | ⏳ pendiente |
| P2-1 | Práctica 2 · Integración Wazuh (push + pull) | ✅ |
| P2-2 | Práctica 2 · Informe de incidente en PDF | ✅ |
| P2-3 | Práctica 2 · Respuestas ES/EN con detección automática | ✅ |
| P2-4 | Práctica 2 · MFA TOTP obligatorio | ✅ |

Detalle de la Práctica 2 en [docs/14-practica2.md](docs/14-practica2.md).

Detalle por fase en [docs/02-estado-fases.md](docs/02-estado-fases.md).

---

## Equipo y soporte

- Repo: <https://github.com/f3l0X/soc-copilot>
- Issues: <https://github.com/f3l0X/soc-copilot/issues>
- Para incidencias en producción, contacta al admin de la instancia.

---

## Licencia

MIT — ver [LICENSE](LICENSE).
