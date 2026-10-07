# Guia de trabajo para el equipo

## Que contiene el comprimido / repo

- Código fuente de backend y frontend.
- Infraestructura Docker local.
- Documentación del proyecto (`docs/`).
- Workflows de CI (`.github/workflows/`).
- `.env.example`.

No incluye:

- `.env` real.
- `node_modules`, `.next`, `__pycache__` (todos `.gitignore`'d).
- Volúmenes/bases de datos locales.

Cada persona crea su `.env` a partir de `.env.example`.

## Flujo recomendado para empezar

1. Leer [01-instalacion-local.md](01-instalacion-local.md).
2. Levantar el stack con Docker Compose.
3. Registrar tu usuario en `/login` (el primero del equipo es admin).
4. Probar `/alerts`, `/respond`, `/history`, `/chat`.
5. Leer [02-estado-fases.md](02-estado-fases.md) y [03-arquitectura.md](03-arquitectura.md).
6. Coordinar tareas antes de modificar áreas compartidas.

## Reparto funcional sugerido (5 personas)

| Persona | Foco principal | Áreas del repo |
|---------|----------------|----------------|
| **P1** Tech Lead / Backend Core | FastAPI, LLM adapter, schemas | `apps/api/app/{main,config,routers,schemas}`, `services/llm.py` |
| **P2** RAG / Knowledge | Ingestión, retrieval, prompts del chat | `services/{rag,chat}.py`, `scripts/ingest_kb.py`, `scripts/owasp_top10.py` |
| **P3** Backend Servicios / Auth / DB | Auth, RBAC, persistencia, tests | `services/{auth,explainer,recommender}.py`, `models.py`, `db.py`, `middleware/`, `tests/` |
| **P4** Frontend Lead | Dashboard, alerts, respond, history | `apps/web/src/app/{alerts,respond,history,page}.tsx`, `components/RiskBadge.tsx` |
| **P5** Frontend Chat + DevOps | Chat, login, auth UI, Docker, CI, deploy | `apps/web/src/app/{chat,login}/`, `lib/{auth,api}.tsx`, `infra/`, `.github/workflows/` |

Cada persona tiene archivos donde su contribución es identificable, lo
que cubre el requisito de la rúbrica («funcionalidades diferenciadas por
miembro»).

## Convenciones actuales

- Backend bajo `apps/api/app`. Tests bajo `apps/api/tests`. Scripts CLI
  bajo `apps/api/scripts`. Configuración de lint en `apps/api/ruff.toml`.
- Frontend bajo `apps/web/src`. Lint en `apps/web/eslint.config.mjs`
  (ESLint 9 flat config con `next/core-web-vitals`).
- Endpoints API bajo prefijo `/api`. Detalle en
  [06-api-reference.md](06-api-reference.md).
- Variables compartidas en `.env`. Secretos rotables documentados en
  `.env.example`.
- Desarrollo local exclusivamente con Docker Compose: no hace falta
  instalar Python/Node/Postgres en el host.

## Validación antes de entregar cambios

### Backend

```bash
cd infra
docker compose exec api ruff check app tests
docker compose exec api pytest -q
```

Resultado esperado: `All checks passed!` y `69 passed, 1 skipped`.

### E2E con DB real (opcional, lento)

```bash
cd infra
docker compose exec api sh -c "RUN_E2E=1 pytest -q tests/test_e2e.py"
```

Resultado esperado: `2 passed`.

### Frontend

```bash
cd infra
docker compose exec web npx tsc --noEmit
docker compose exec web npm run lint
docker compose exec web npm run build
```

Resultado esperado: `Compiled successfully` + 9 rutas estáticas.

### Auditoría de dependencias

```bash
cd apps/web
docker run --rm -v "$PWD:/app" -w /app node:22-bookworm-slim \
  sh -c "npm ci --no-audit --no-fund && npm audit --audit-level=high"
```

Resultado esperado: 0 high. Aceptamos las 2 moderate de `postcss` que
viene vendored dentro de Next.js (documentado en
[security.md](security.md)).

### Smoke manual rápido

1. Login con tu usuario.
2. `/alerts` → analizar un log de ejemplo.
3. `/respond` → recomendar acciones desde la alerta creada.
4. `/history` → ver tu alerta listada con su risk badge.
5. `/chat` → preguntar sobre alguna técnica MITRE.

## Puntos importantes antes de desarrollar

- **Nunca subir claves reales de Gemini ni `.env` personales** al repo.
  `.env` está en `.gitignore`; verificar con `git status` antes de
  commit.
- **Cambios de schema DB**: se hacen vía Alembic. Generar la revisión
  con `alembic revision --autogenerate -m "..."` desde `apps/api`
  (o dentro del contenedor api). **Siempre revisar el archivo generado**
  antes de aplicarlo: autogenerate trata renames como drop + add.
  `init_db()` corre `alembic upgrade head` al arrancar. Si rompes algo,
  `docker compose down -v` reinicia el volumen pero tira las alertas
  guardadas y la KB RAG (re-ingerir con `python -m scripts.ingest_kb`).
  Detalle en [RUNBOOK.md §3](RUNBOOK.md#3-migraciones-alembic).
- **Tests**: si añades funcionalidad backend, el patrón es
  service-level con fakes (sin DB) en `test_smoke.py` o `test_auth.py`.
  Para flujos que necesitan DB real, en `test_e2e.py` (sólo se ejecuta
  con `RUN_E2E=1`).
- **Lint backend**: ruff aplica `E,F,W,I,B,UP,RUF` con `line-length=100`.
  Configuración en `apps/api/ruff.toml`.
- **Lint frontend**: ESLint 9 flat con preset `next/core-web-vitals` y
  `next/typescript`. Config en `apps/web/eslint.config.mjs`.

## CI: qué se ejecuta en cada push

Dos workflows:

`.github/workflows/ci.yml` (en cada push y PR):

| Job | Steps |
|-----|-------|
| `api` | `pip install`, `ruff check app tests`, smoke import, `pytest -q` |
| `web` | `npm ci`, `npm audit --audit-level=high`, `npm run lint`, `npm run build` |
| `infra` | `docker compose config` (valida sintaxis del compose) |

`.github/workflows/e2e.yml` (push a `main` y `workflow_dispatch`): levanta
Postgres 16, ejecuta `alembic upgrade head`, `alembic check` y la suite
completa de E2E + migraciones.

Todos deben pasar para que un PR se considere mergeable. Detalle en
[07-testing.md](07-testing.md).

## Antes de un release / entrega

- [ ] CI verde en `main`.
- [ ] Cold-start en local OK: `docker compose down -v && docker compose up --build -d`.
- [ ] KB re-ingerida (`docker compose exec api python -m scripts.ingest_kb`).
- [ ] Smoke manual de las 4 pantallas + login/logout.
- [ ] [security.md](security.md) actualizado si hay cambios sensibles.
- [ ] [02-estado-fases.md](02-estado-fases.md) actualizado.
- [ ] Roadmap revisado.
