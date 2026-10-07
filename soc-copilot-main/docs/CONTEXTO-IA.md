# Contexto del Proyecto — SOC Copilot (Blue Team)

> Documento autocontenido para pasar a otra IA o a una nueva sesión.
> Última actualización: 2026-05-14.

## 1. Qué es el proyecto

**AI Copilot para Analistas SOC Junior** — Práctica 1 del Módulo Ciberseguridad Avanzada (Curso 2026).
Trabajo universitario en grupo de 5 personas (línea Blue Team), con "alcance completo" exigido por la rúbrica.

**Fechas clave**
- Inicio: 2026-04-25
- Entrega: **2026-05-25**

**Entregables obligatorios**
- Dashboard web funcional.
- Repo GitHub.
- Despliegue en **Hetzner Cloud VPS** (live para la demo).
- Informe PDF profesional.
- Demo oral 10 min.

**Pesos de evaluación**: 30% funcionalidad · 20% informe PDF · 15% UX dashboard · 15% deploy Hetzner · 10% calidad repo · 10% roadmap.

## 2. Módulos funcionales

1. **Alert Explainer** — LLM + mapeo MITRE ATT&CK (`POST /api/explain`).
2. **Next Step Recommender** — con "modo aprendizaje" (`POST /api/recommend`).
3. **Chat IA con RAG** sobre MITRE + OWASP (`POST /api/chat`).

## 3. Stack técnico (decidido, no rebikeshear)

- **Backend**: Python 3.12 + FastAPI. Adaptador LLM provider-agnostic (`LLMAdapter` / `GeminiAdapter`).
- **LLM**: Gemini (free tier). Embeddings `text-embedding-004`. Chat `gemini-2.5-flash` y `gemini-2.5-flash-lite` con allowlist server-side.
- **RAG / vector store**: ChromaDB embebida, colección `soc_kb` (~700 docs: 691 MITRE + 10 OWASP).
- **DB relacional**: PostgreSQL 16. Migraciones con **Alembic**.
- **Frontend**: Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui.
- **Auth**: JWT HS256 + bcrypt, cookie `soc_session` httpOnly SameSite=Lax. RBAC dinámico (matriz editable por admin).
- **Orquestación**: Docker Compose (dev y prod).
- **Reverse proxy prod**: Caddy 2 (HTTPS automático).
- **CI**: GitHub Actions (ruff + pytest + `next build` + Playwright E2E).
- **OS dev**: Windows 11 + WSL2 + Docker Desktop.

**Puertos locales**: Frontend `13500`, API `8080`, Postgres `55432` (5432–5757 reservados por Hyper-V en Windows), Chroma `8001`.

## 4. Estructura del repo

```
D:\Evolve\Proyecto Blue Team\soc-copilot\
├── apps/
│   ├── api/        FastAPI (app/, alembic/, scripts/ingest_kb.py, tests/)
│   └── web/        Next.js 15 (e2e/ Playwright)
├── infra/
│   ├── docker-compose.yml              dev
│   ├── docker-compose.prod.example.yml plantilla Hetzner
│   ├── caddy/
│   └── postgres/
├── docs/           00-indice → 11-modulo-auditoria, RUNBOOK.md, roadmap.md, security.md
├── scripts/
├── .github/workflows/   ci.yml, e2e.yml
├── .env.example
└── README.md
```

Documentación viva en `docs/` (numerada 00–11). Estado de fases en `docs/02-estado-fases.md`. Runbook operativo en `docs/RUNBOOK.md`.

## 5. Estado de fases

- **Fase 0** Base monorepo + Docker + CI ✅
- **Fase 1** Alert Explainer ✅
- **Fase 2** Next Step Recommender + persistencia (Alert, Recommendation, Alembic) ✅
- **Fase 3** RAG + Chat IA (ingest_kb idempotente, citaciones clicables) ✅
- **Fase 4** Auth + RBAC dinámico + panel admin (4 pestañas: usuarios/roles/permisos/auditoría) + tests E2E ✅
- **Pendiente**: deploy Hetzner final, informe PDF, polish UX, demo.

## 6. Reparto del equipo (5 personas)

- **P1** Tech Lead / Backend Core (FastAPI, LLM adapter, `/explain`)
- **P2** RAG / Knowledge Eng (ingest MITRE+OWASP, `/chat`)
- **P3** Backend Services (Recommender, auth, persistencia)
- **P4** Frontend Lead (dashboard, `/alerts`, `/respond`)
- **P5** Frontend Chat + DevOps (chat UI, Docker, Hetzner, CI)

La rúbrica exige funcionalidades diferenciadas por miembro.

## 7. Seguridad ya implementada

- Errores LLM saneados (502 genérico al cliente; detalle solo en logs).
- Mitigación prompt injection: logs de usuario envueltos en `BEGIN_UNTRUSTED_LOG`/`END_UNTRUSTED_LOG`, KB en `BEGIN_UNTRUSTED_KB`/`END_UNTRUSTED_KB`.
- Rate limit por IP en `/explain` y `/recommend` (ventana deslizante en memoria, configurable).
- Validación Pydantic estricta (longitudes, no whitespace, modelo en allowlist).
- Logs JSON estructurados en prod con eventos estandarizados (`auth.login`, `llm.call`, `alert.created`, `admin.action`, etc.).

## 8. Preferencias del usuario (importantes)

- **Idioma**: español siempre.
- **OS**: Windows 11, rutas tipo `D:\...`. Todo debe funcionar en Windows.
- **Estilo de respuesta**: breve, sin preámbulos, sin pros/cons salvo decisión arquitectónica real.
- **Autonomía**: instalar, configurar, comprobar el equipo sin pedir permiso. Confirmar solo antes de acciones destructivas o que afectan estado compartido (git push, deploy, borrar).
- **Código**: completo y funcional, nunca esqueletos vacíos. JSON estructurado sin texto envolvente cuando aplique. Cambiar una cosa a la vez al refinar. Decir "no lo sé" antes que inventar versiones/configs.
- **Identificar antes de codear**: lenguaje, framework, entorno, versiones.
- **Self-review tras cada respuesta**: qué puede fallar, qué asumí, qué verificar antes de prod.

Reglas completas en `D:\Evolve\Proyecto Blue Team\CÓMO DEBES RESPONDER A MIS PROMPTS.txt`.

## 9. Tooling local

- **RTK (Rust Token Killer)** instalado global como hook PreToolUse de Bash. Reescribe comandos transparentemente (`git status` → `rtk git status`). Verificar con `rtk --version` y `rtk gain`.
- Vault Obsidian en la raíz del proyecto (`.obsidian/`) — los `.md` son ciudadanos de primera clase.
- API key de Gemini ya provisionada (estuvo en plaintext en repo, ya flagged).

## 10. Próximos pasos lógicos

1. Cerrar deploy Hetzner con `docker-compose.prod.example.yml` + Caddy + dominio.
2. Redactar informe PDF profesional (rúbrica = 20%).
3. Polish UX dashboard (rúbrica = 15%).
4. Ensayar demo oral 10 min.
5. Limpieza repo y roadmap final (rúbrica = 10% + 10%).
