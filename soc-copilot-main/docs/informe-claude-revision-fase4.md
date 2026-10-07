# Informe para Claude Code - Revision Fase 4

## Contexto

Proyecto: SOC Copilot.

Estado observado:

- Fase 2 terminada.
- Fase 3 parcialmente implementada: `/api/chat`, RAG, ChromaDB, `/api/kb/status`, `/api/llm/models`, scripts de ingesta y UI `/chat`.
- Fase 4 ya empezo parcialmente: auth backend/frontend, login, registro, cookies JWT, RBAC basico y tests nuevos.
- No hay cambios pendientes en git en el momento de la revision.

## Resultado de verificacion

Comandos ejecutados:

```bash
cd infra
docker compose config --quiet
```

Resultado: OK.

```bash
cd infra
docker compose run --rm --no-deps -v "D:\Evolve\Nueva carpeta (2)\soc-copilot\apps\api\tests:/code/tests:ro" api ruff check app tests
```

Resultado: OK.

```bash
cd infra
docker compose run --rm --no-deps -v "D:\Evolve\Nueva carpeta (2)\soc-copilot\apps\api\tests:/code/tests:ro" api pytest -q
```

Resultado: OK. `69 passed`, `1 skipped`, `1 warning`.

```bash
cd apps/web
npm run build
```

Resultado: fallo local. `next` no se reconoce porque falta `node_modules/.bin/next.cmd`.

```bash
cd apps/web
npm run lint
```

Resultado: fallo local por la misma causa. Ademas, el script sigue usando `next lint`, que esta deprecado y no es no-interactivo.

```bash
cd apps/web
npm audit --json
```

Resultado:

- 0 critical.
- 0 high.
- 2 moderate por `postcss` embebido dentro de `next`.

## Problemas detectados

### 1. Riesgo alto: cambio de esquema sin migracion

Se añadieron:

- tabla `users`.
- columna `alerts.user_id`.

Pero el proyecto sigue usando `Base.metadata.create_all()` en el arranque.

Problema:

- `create_all()` crea tablas nuevas.
- No altera tablas existentes.
- Si alguien ya tiene un volumen PostgreSQL de fases anteriores, la tabla `alerts` no tendra la columna `user_id`.
- En ese caso, `/api/explain` puede fallar al guardar una alerta porque intenta escribir `user_id`.

Solucion requerida:

- Para desarrollo, documentar claramente que tras fase 4 hay que reiniciar volumen:

```bash
cd infra
docker compose down -v
docker compose up --build -d
```

- Mejor solucion: añadir migracion idempotente.
- Opcion simple sin Alembic:

```sql
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE alerts
  ADD CONSTRAINT alerts_user_id_fkey
  FOREIGN KEY (user_id)
  REFERENCES users(id)
  ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_alerts_user_id ON alerts(user_id);
```

- Opcion mas robusta: introducir Alembic y crear migracion formal.

### 2. Auth incompleto para produccion

Se implemento JWT/cookies y proteccion de endpoints, pero quedan riesgos:

- `jwt_secret` tiene default conocido:

```python
jwt_secret: str = "dev-only-change-me-32+chars-please"
```

- `.env.example` no documenta variables importantes:
  - `JWT_SECRET`
  - `JWT_TTL_SECONDS`
  - `COOKIE_NAME`
  - `COOKIE_SECURE`
- `cookie_secure=False` por defecto.

Solucion requerida:

- Añadir variables auth a `.env.example`.
- Añadirlas tambien a `infra/docker-compose.prod.example.yml`.
- En produccion, exigir:

```env
JWT_SECRET=<valor fuerte generado con openssl rand -base64 48>
COOKIE_SECURE=true
```

- Añadir validacion de arranque si existe variable tipo `APP_ENV=production`:
  - fallar si `JWT_SECRET` sigue siendo el default.
  - fallar si `COOKIE_SECURE=false`.

### 3. Registro publico con primer usuario admin

`/api/auth/register` es publico.

La logica actual:

- primer usuario registrado => `admin`.
- siguientes usuarios => `analyst`.

Esto es aceptable para local, pero peligroso si se levanta el VPS antes de crear el admin.

Riesgos:

- cualquiera que acceda primero al endpoint podria convertirse en admin.
- posible carrera si dos registros simultaneos ocurren cuando no hay usuarios.

Solucion requerida:

- Añadir variable:

```env
AUTH_REGISTRATION_ENABLED=true
```

- En produccion, dejarla en `false` por defecto.
- Añadir un mecanismo de creacion inicial de admin:
  - script CLI.
  - seed controlado por variables.
  - invitacion/admin-only.
- Para evitar carrera:
  - usar transaccion.
  - bloquear o reconsultar antes de asignar admin.
  - idealmente crear admin fuera del registro publico.

### 4. Frontend lint sigue roto/no automatizable

`apps/web/package.json` mantiene:

```json
"lint": "next lint"
```

Problemas:

- `next lint` esta deprecado.
- Puede abrir asistente interactivo.
- No es adecuado para CI.
- En el entorno local actual falla porque falta `node_modules/.bin/next.cmd`.

Solucion requerida:

- Migrar a ESLint CLI.
- Añadir dependencias:

```bash
npm install -D eslint eslint-config-next
```

- Crear config minima si no existe.
- Cambiar script:

```json
"lint": "eslint ."
```

- Verificar:

```bash
npm run lint
npm run build
```

### 5. Build frontend local no verificable ahora mismo

`npm run build` falla con:

```text
"next" no se reconoce como un comando interno o externo
```

Diagnostico:

- `node_modules/next/package.json` existe.
- falta `node_modules/.bin/next.cmd`.
- instalacion local de dependencias incompleta o inconsistente.

Solucion requerida:

```bash
cd apps/web
npm install
npm run build
npm run lint
```

En CI se usa `npm ci`, por lo que podria funcionar alli, pero debe verificarse localmente.

### 6. Ingesta RAG aun depende de red/cuota

`apps/api/scripts/ingest_kb.py` aun no tiene:

- `--dry-run`
- `--sample`

Problema:

- descarga MITRE desde GitHub.
- embebe con Gemini.
- puede fallar por red, Chroma apagado o cuota agotada.
- no hay modo barato/offline para que compañeros prueben `/chat`.

Solucion requerida:

- Añadir `--dry-run`:
  - valida Chroma.
  - prepara documentos.
  - cuenta documentos.
  - no llama a Gemini.
  - no escribe en Chroma.
- Añadir `--sample`:
  - usa documentos locales.
  - maximo 10-20 docs.
  - no depende de internet.
  - gasta poca cuota.
- Mejorar mensajes:
  - Chroma caido:

```text
Chroma unavailable. Start docker compose service chroma.
```

  - cuota Gemini:

```text
Gemini quota exhausted. Try --sample, --owasp-only or wait for quota reset.
```

- Crear documentacion:

```text
docs/rag-ingestion.md
```

### 7. Docker local no monta tests

`infra/docker-compose.yml` no monta `apps/api/tests`.

Por eso para ejecutar tests en contenedor hubo que usar un montaje manual:

```bash
docker compose run --rm --no-deps -v "D:\Evolve\Nueva carpeta (2)\soc-copilot\apps\api\tests:/code/tests:ro" api pytest -q
```

Solucion requerida:

Añadir al servicio `api` en `infra/docker-compose.yml`:

```yaml
volumes:
  - ../apps/api/app:/code/app
  - ../apps/api/tests:/code/tests
```

Verificar despues:

```bash
cd infra
docker compose exec api pytest -q
docker compose exec api ruff check app tests
```

### 8. CI incompleto

El workflow actual ejecuta:

- backend tests.
- backend ruff solo sobre `app`.
- e2e backend.
- web build.

Pero no ejecuta:

- lint frontend.
- `npm audit`.
- `ruff check app tests`.

Solucion requerida:

- Cambiar:

```yaml
- run: ruff check app
```

por:

```yaml
- run: ruff check app tests
```

- Añadir en job web:

```yaml
- run: npm audit --audit-level=high
- run: npm run lint
- run: npm run build
```

Nota: primero hay que arreglar `npm run lint`.

### 9. `npm audit` mantiene vulnerabilidades moderadas

Estado:

- 0 critical.
- 0 high.
- 2 moderate.

Origen:

- `postcss <8.5.10` embebido dentro de `next`.
- `next` aparece afectado via `postcss`.

Solucion requerida:

- No aplicar downgrade raro sugerido por `npm audit`.
- Documentar residual si no hay fix limpio dentro de Next 15.x.
- Revisar periodicamente si Next 15 publica parche que actualice su PostCSS interno.
- Mantener `npm audit --audit-level=high` como gate CI minimo.

### 10. Documentacion de seguridad desactualizada

`docs/security.md` todavia indica que auth esta pendiente o habla de NextAuth, pero el proyecto ya implemento auth propia con JWT/cookies.

Solucion requerida:

- Actualizar `docs/security.md`:
  - auth actual: JWT HS256 en cookie httpOnly.
  - rol admin/analyst.
  - endpoints protegidos.
  - limitaciones pendientes.
  - riesgos de registro publico.
  - configuracion requerida en produccion.

## Nota sobre mojibake

En salidas de PowerShell se ven textos rotos como `quÃ©`, `â€”`, etc.

Pero la busqueda en archivos solo encontro esos patrones dentro de `docs/prompt-claude-code-fase4.md`, donde estan listados como ejemplos del problema.

Conclusiones:

- Puede que muchos textos esten bien en UTF-8 y PowerShell los muestre mal.
- Antes de cambiar masivamente, verificar con editor UTF-8 o lectura binaria.
- No aplicar reemplazos globales sin confirmar, porque podria corromper texto correcto.

## Reglas de trabajo para solucionar

- No tocar `.env` real.
- No introducir secretos.
- No borrar datos ni volumenes sin aviso.
- No desplegar a Hetzner.
- No convertir `docker-compose.yml` local en produccion.
- Mantener compatibilidad con Windows + Docker Desktop.
- Mantener tests backend existentes pasando.
- Si se actualizan dependencias, actualizar lockfiles.
- Si se cambia esquema DB, documentar migracion o reset de volumen.

## Verificacion obligatoria esperada

Backend:

```bash
cd infra
docker compose config --quiet
docker compose up -d postgres chroma api
docker compose exec api ruff check app tests
docker compose exec api pytest -q
```

Frontend:

```bash
cd apps/web
npm install
npm audit --audit-level=high
npm run lint
npm run build
```

RAG:

```bash
cd infra
docker compose exec api python -m scripts.ingest_kb --dry-run
docker compose exec api python -m scripts.ingest_kb --sample
curl http://localhost:8080/api/kb/status
```

Auth:

```bash
curl -i http://localhost:8080/api/alerts
```

Debe devolver `401` sin sesion.

Despues de login/registro, endpoints protegidos deben funcionar solo con cookie/token valido.

## Entrega esperada

Al terminar, reportar:

- Archivos modificados.
- Problemas corregidos.
- Comandos ejecutados y resultados.
- Estado de tests backend.
- Estado de build/lint frontend.
- Estado de `npm audit`.
- Estado de `/api/kb/status`.
- Como migrar o resetear DB local tras cambios de auth.
- Pendientes reales para fase 5.

