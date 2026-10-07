# Solucion de problemas

## Docker no arranca

Comprobar que Docker Desktop está abierto y el motor iniciado.

En Windows, comprobar también:

- WSL2 instalado (`wsl --status`).
- Virtualización habilitada en BIOS/UEFI.
- Docker Desktop configurado para usar WSL2.

Si Docker Desktop arranca y se queda colgado con el error
`initializing Inference manager: listening on unix://C:\...\dockerInference`,
el bug es del propio Docker Desktop (Windows) en algunas versiones que
incluyen Docker Model Runner. Workaround:

1. Renombrar `C:\Program Files\Docker\Docker\resources\model-runner` a
   `model-runner.disabled`.
2. `wsl --shutdown` y relanzar Docker Desktop.

Si persiste: reinstalar Docker Desktop (no perdemos volúmenes ni KB
porque viven dentro de WSL en `docker-desktop-data`).

## Puerto ocupado

Puertos por defecto:

| Servicio | Host | Container |
|----------|------|-----------|
| Frontend | 13500 | 3000 |
| API | 8080 | 8080 |
| Postgres | 55432 | 5432 |
| Chroma | 8001 | 8000 |

En **Windows 11 con Hyper-V** muchos puertos bajos están reservados
dinámicamente. Verificar con:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

Si tu rango excluido toca uno de los puertos host actuales:

- Cambia el binding en `infra/docker-compose.yml` (`ports: "<nuevo>:<container>"`).
- Actualiza `.env` (`API_CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`,
  `NEXTAUTH_URL`) si cambias el puerto del frontend.

## La API responde 502 «AI provider error»

Causa: la llamada a Gemini falló. La sanitización oculta el detalle al
cliente; los logs internos lo tienen. Para verlo:

```bash
cd infra
docker compose logs api --since 5m | grep -E "(LLM|429|RESOURCE_EXHAUSTED|ClientError)"
```

Diagnósticos comunes:

| Mensaje | Causa | Solución |
|---------|-------|----------|
| `429 RESOURCE_EXHAUSTED ... GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20` | Cuota diaria del free tier agotada | Cambiar de modelo en el selector de la UI (allowlist) o esperar al reset (00:00 PT = ~09:00 CEST) |
| `404 NOT_FOUND models/...` | Modelo retirado o sin acceso para esta key | Revisar `GEMINI_CHAT_MODELS_ALLOWLIST` y dejar solo modelos accesibles |
| `GEMINI_API_KEY is not configured` | `.env` con `replace_me` | Editar `.env` con la clave real y `docker compose up -d` (no `restart`, hace falta releer el env_file) |

## La API responde 502 «AI response could not be processed»

Gemini contestó pero el JSON no validó contra nuestro schema. Suele pasar
si cambias el modelo a uno que no soporta `response_schema`. Pasa al
default (`gemini-2.5-flash-lite`) desde el selector.

## La API responde 401 al cargar /alerts u otras

El endpoint exige sesión y la cookie no está presente o expiró (TTL 1h
por defecto). Vuelve a `/login`.

Si la cookie sí existe pero igualmente da 401, comprobar:

- `JWT_SECRET` cambió desde el login → todos los tokens previos invalidados.
  Volver a entrar.
- Reloj del contenedor desincronizado: `docker compose exec api date`.

## La API responde 429 «rate limit exceeded»

Has hecho más de `RATE_LIMIT_REQUESTS` peticiones a `/api/explain`,
`/api/recommend` o `/api/chat` en menos de `RATE_LIMIT_WINDOW_SECONDS`
desde la misma IP. Defaults: 20 req / 60s.

Para tests/load: subir el límite o desactivarlo en `.env`:

```env
RATE_LIMIT_ENABLED=false
```

y `docker compose up -d api`.

## El frontend no conecta con la API

Comprobar que la API está viva:

```bash
curl http://localhost:8080/api/health
```

Respuesta esperada: `{"status":"ok"}`.

Comprobar `.env`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8080
API_CORS_ORIGINS=http://localhost:13500
```

## Cambios en frontend no aparecen

Bind-mount + Next dev a veces no detecta cambios desde Windows. Force-poll
ya está activo (`WATCHPACK_POLLING=true`). Si aún así nada se actualiza:

```bash
cd infra
docker compose restart web
```

Si persiste:

```bash
docker compose up --build -d web
```

## El chat dice «KB no disponible»

`/api/kb/status` devuelve error o cuenta cero. Pasos:

1. Verificar que Chroma está corriendo: `docker compose ps chroma`.
2. Re-ingerir base de conocimiento (la primera vez, o tras `down -v`):

   ```bash
   docker compose exec api python -m scripts.ingest_kb
   ```

3. Verificar:

   ```bash
   curl http://localhost:8080/api/kb/status
   ```

   Debe devolver `{"total":700+, "mitre":690+, "owasp":10}`.

Detalle completo en [08-rag-ingestion.md](08-rag-ingestion.md).

## Migrar / resetear la DB local tras cambios

El stack usa **Alembic**. `init_db()` ejecuta `alembic upgrade head` al
arrancar el API y hace `alembic stamp head` sobre DBs legacy creadas con
`create_all`. **No hace falta** `down -v` para la mayoría de cambios:
basta con `docker compose up -d --build api` y la migración corre sola.

Sí necesitas reset cuando:

- Una migración falla a mitad y deja el schema inconsistente.
- Renombramos columnas y la migración autogenerada las trataría como
  drop + add (revisar siempre el archivo generado, ver
  [RUNBOOK.md §3](RUNBOOK.md#3-migraciones-alembic)).
- Pruebas E2E quieren DB limpia.

```bash
cd infra
docker compose down -v
docker compose up --build -d
docker compose exec api python -m scripts.ingest_kb   # poblar KB de nuevo
```

## El build tarda mucho la primera vez

Es normal. Docker descarga imágenes base e instala dependencias de Python
y Node. Builds posteriores reutilizan capas.

## Comprobar estado de contenedores

```bash
cd infra
docker compose ps
```

## Ver logs

| Caso | Comando |
|------|---------|
| Todos | `docker compose logs -f` |
| Solo API | `docker compose logs -f api` |
| Solo frontend | `docker compose logs -f web` |
| Errores LLM en últimos 10 min | `docker compose logs api --since 10m \| grep -E "(LLM|429|ERROR)"` |

## El primer registro me dio rol analyst, no admin

`/api/auth/register` mira si la tabla `users` está vacía. Si alguien (tú
mismo en otra sesión, o un teammate) se registró antes, ya hay un admin.
Para promocionarte:

```bash
docker compose exec postgres psql -U soc -d soc_copilot \
  -c "UPDATE users SET role='admin' WHERE email='tu@email.com';"
```

## Cookie de sesión no se guarda en el navegador

- Verificar que el frontend hace fetch con `credentials: 'include'` (ya
  está en `lib/api.ts`).
- En dev sin HTTPS, `COOKIE_SECURE=false` (default).
- En prod tras HTTPS Caddy, debe ser `true`.

## ESLint/build frontend pide `node_modules`

Si quieres ejecutar `npm run lint` o `build` directamente en host
(fuera de Docker), instala primero:

```bash
cd apps/web
npm ci
```

Pero el flujo habitual es dentro del contenedor:

```bash
docker compose exec web npm run lint
docker compose exec web npm run build
```

## Producción (Hetzner): incidencias frecuentes

Estas son las incidencias específicas del entorno productivo. Cobertura
completa en [operations.md](operations.md).

### "Failed to fetch" en el navegador tras un deploy

Casi siempre **cache** del navegador sirviendo el bundle viejo. En
DevTools → Network → **Disable cache** y Ctrl+Shift+R. Si persiste,
verifica que `NEXT_PUBLIC_API_URL` quedó embebido en el bundle nuevo:
```bash
dc exec web sh -c "grep -ro 'soc-copilot.duckdns.org' .next/static/chunks/ | head -1"
```
Si está vacío, falta rebuild forzado del `web` con `--no-cache`.

### El registro devuelve 500 tras añadir una columna nueva

Migración no aplicada. Ejecuta:
```bash
dc exec api alembic upgrade head
dc exec api alembic current
```
Debe terminar en la última revisión disponible (`(head)`). Si no, busca
si `git pull` falló silenciosamente por un patch local — ver el caso
en operations.md sección 2.

### `git pull` aborta con "Your local changes would be overwritten"

Hay un patch manual en el server fuera del repo (típicamente del
deploy inicial). Compara con `git diff <archivo>`; si es funcionalmente
equivalente al de upstream, descarta el local:
```bash
git checkout -- <archivo>
git pull --ff-only
```

### No llega el email de verificación

Probables causas, en orden:
1. SMTP no configurado o credenciales mal: revisa `dc logs api | grep email`.
2. El email cayó en **spam** del Gmail destinatario.
3. App Password de Gmail caducada o revocada — genera una nueva en
   <https://myaccount.google.com/apppasswords> y actualiza
   `SMTP_PASSWORD` en `.env`. Reinicia el `api` con `dc up -d api`.
4. Solo a efectos de unblock inmediato: el admin puede marcar el
   usuario como verificado con
   `UPDATE users SET is_verified=true, email_verified_at=now() WHERE email='...'`.

### "El registro está cerrado temporalmente" en pruebas

El admin tiene `ALLOW_PUBLIC_REGISTRATION=false` y/o el toggle en BD
en `false`. Vía rápida: `/admin → Usuarios → Registro público → Abrir`.
Vía CLI: ver [operations.md §4](operations.md). Recuerda cerrarlo
después de la prueba.

### Cuota de Gemini agotada durante ingesta KB

El free tier tiene cuota DIARIA estricta. Si el script entra en bucle
de 429 con backoff y nunca avanza, espera al reset (00:00 PT ≈ 09:00
hora España) o activa billing pay-as-you-go en Google AI Studio
(coste real ~0,01 € por las 707 técnicas).
