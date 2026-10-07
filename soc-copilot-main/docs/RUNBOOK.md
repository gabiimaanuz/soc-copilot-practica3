# RUNBOOK operativo — SOC Copilot

Guía práctica para desplegar, operar y recuperar el servicio en producción
(Hetzner VPS + Docker Compose + Caddy). Pensado para que cualquiera del
equipo pueda ejecutar las tareas críticas sin "magia oral".

> Convenciones: los comandos asumen que estás en la raíz del repo
> (`soc-copilot/`) salvo que se indique otra cosa. Las rutas usan `/`
> aunque el desarrollo local sea Windows; en el VPS todo es Linux.

---

## 1. Despliegue inicial en Hetzner

### 1.1 Pre-requisitos

- VPS con Ubuntu 22.04+ (CX22 o superior) y acceso SSH como root o
  usuario con `sudo`.
- Docker Engine + Docker Compose v2 (`docker compose version` debe
  responder `>= 2.x`).
- Dominio (`tu-dominio.example`) con un registro `A` apuntando a la IP
  pública del VPS. Caddy emitirá el certificado TLS automáticamente vía
  Let's Encrypt en el primer arranque.
- Puertos `80/tcp`, `443/tcp` y `443/udp` abiertos en el firewall.

### 1.2 Variables de entorno (`.env`)

Coloca el `.env` en la raíz del repo (NO en `infra/`). El compose de
producción lo monta vía `env_file: ../.env`. Está en `.gitignore`.

Variables obligatorias:

```ini
# Marca el entorno como prod — habilita validaciones estrictas y
# desactiva /docs, /redoc, /openapi.json. Si falta, el API arranca
# con afordances de desarrollo.
APP_ENV=production

# Gemini global (fallback cuando el usuario no tiene BYO key).
# Obtener en https://aistudio.google.com/apikey
GEMINI_API_KEY=AIza...
GEMINI_CHAT_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=gemini-embedding-001

# Postgres
POSTGRES_USER=soc
POSTGRES_PASSWORD=<rotado, fuerte, ver §1.3>
POSTGRES_DB=soc_copilot
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Chroma (vector store)
CHROMA_HOST=chroma
CHROMA_PORT=8000

# Auth — ver §1.3 para generarlos
JWT_SECRET=<base64 48 bytes>
APP_ENCRYPTION_KEY=<Fernet key urlsafe-b64 32 bytes>

# CORS — debe coincidir con el dominio público real
API_CORS_ORIGINS=https://tu-dominio.example

# Frontend
NEXT_PUBLIC_API_URL=https://tu-dominio.example
PUBLIC_DOMAIN=tu-dominio.example
ACME_EMAIL=admin@tu-dominio.example

# Rate limit (deja los defaults salvo necesidad)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=20
RATE_LIMIT_WINDOW_SECONDS=60

# Quota diaria por usuario sobre la GEMINI_API_KEY global
SERVER_LLM_DAILY_QUOTA=50

# Bootstrap del primer admin — ver §1.5
ALLOW_PUBLIC_REGISTRATION=true
```

> ⚠️ Si `APP_ENV=production` y alguno de los secretos sigue en su valor
> por defecto, el API se niega a arrancar con
> `Refusing to start with insecure configuration`. Es intencional.

### 1.3 Generación de secretos

```bash
# JWT_SECRET — sesiones firmadas (>=32 chars)
openssl rand -base64 48

# APP_ENCRYPTION_KEY — Fernet, urlsafe-b64 de 32 bytes
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# POSTGRES_PASSWORD — cualquier cadena fuerte; evitar 'postgres', 'change_me'
openssl rand -base64 32
```

### 1.4 Levantar el stack

```bash
git clone https://github.com/f3l0X/soc-copilot.git
cd soc-copilot
# Copia y rellena el .env (ver §1.2)
cp .env.example .env
$EDITOR .env

cd infra
docker compose -f docker-compose.prod.example.yml --env-file ../.env up -d

# Comprobar arranque
docker compose -f docker-compose.prod.example.yml ps
docker compose -f docker-compose.prod.example.yml logs -f api
```

El primer arranque tarda ~3 min (build de imágenes + descarga de bases).
Las migraciones Alembic se aplican automáticamente en el lifespan del
API (`init_db()` ejecuta `alembic upgrade head`).

### 1.5 Crear el primer admin

El primer registro vía `/api/auth/register` se promueve a `ADMIN`
automáticamente. Después hay que blindar el flujo:

```bash
# 1. Registra el admin desde el frontend (https://tu-dominio.example/login)
#    o por API:
curl -X POST https://tu-dominio.example/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@tu-dominio.example","password":"...","name":"Admin"}'

# 2. Apaga el registro público en .env
ALLOW_PUBLIC_REGISTRATION=false

# 3. Reinicia solo el API
docker compose -f infra/docker-compose.prod.example.yml --env-file .env up -d --force-recreate api
```

A partir de ahora, los nuevos usuarios se crean desde el panel admin
(`/admin/users`) o por API (`POST /api/admin/users`).

### 1.6 Ingestar la KB inicial (MITRE ATT&CK + OWASP Top 10)

El módulo de chat usa una colección Chroma `soc_kb`. La primera vez hay
que poblarla:

```bash
docker compose -f infra/docker-compose.prod.example.yml exec api \
  python -m scripts.ingest_kb
```

El script es idempotente y tarda 5–15 min según RPM disponibles del free
tier de Gemini (~700 documentos en lotes con backoff exponencial).
Variantes:

```bash
# Re-ingerir todo desde cero
docker compose ... exec api python -m scripts.ingest_kb --force

# Solo OWASP (mucho más rápido, útil para smoke tests)
docker compose ... exec api python -m scripts.ingest_kb --owasp-only
```

---

## 2. Rotación de secretos

Esta es la sección más crítica del runbook. Lee entera antes de tocar
nada.

### 2.1 `JWT_SECRET`

Firma todos los JWT de sesión. Rotar invalida **todas las sesiones
activas**: cada usuario tendrá que volver a hacer login. No hay forma
de migrar gradualmente sin overlap (no soportamos firmas múltiples).

```bash
# 1. Generar el nuevo valor
NEW_JWT=$(openssl rand -base64 48)

# 2. Editar .env y reemplazar JWT_SECRET=$NEW_JWT

# 3. Reiniciar SOLO el API (no hace falta tocar postgres ni chroma)
docker compose -f infra/docker-compose.prod.example.yml --env-file .env \
  up -d --force-recreate api
```

Frecuencia recomendada: cada 90 días o ante cualquier sospecha de
filtración del secreto.

### 2.2 `APP_ENCRYPTION_KEY` ⚠️

Cifra las claves Gemini BYO de cada usuario en la columna
`users.gemini_api_key_ciphertext`. **Rotarla rompe el descifrado de
todas las claves BYO existentes.**

El código tiene un fallback graceful: si una ciphertext no se puede
descifrar, el adapter cae a la `GEMINI_API_KEY` global del servidor (con
la cuota diaria), loggea `llm.byo_decrypt_failed` y sigue funcionando.
Los usuarios afectados verán una bajada de funcionalidad pero no errores
500.

Procedimiento recomendado:

```bash
# 1. Avisar a los users por adelantado (banner UI, mail, lo que toque):
#    "El día X rotaremos la clave maestra. Tendrás que volver a
#    introducir tu clave Gemini en /settings/llm."

# 2. Generar la nueva key
NEW_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 3. Reemplazar APP_ENCRYPTION_KEY en .env

# 4. Reiniciar el API
docker compose ... up -d --force-recreate api

# 5. (Opcional) Limpiar las ciphertext huérfanas para que cada user
#    vea "no key configured" en /settings/llm en vez del fallback al
#    server-key:
docker compose ... exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c \
  "UPDATE users SET gemini_api_key_ciphertext = NULL,
                    gemini_key_last4 = NULL,
                    gemini_key_validated_at = NULL
   WHERE gemini_api_key_ciphertext IS NOT NULL;"

# 6. Los users vuelven a /settings/llm y pegan su clave; el API la
#    valida con un ping y la cifra con la nueva master key.
```

### 2.3 `POSTGRES_PASSWORD`

La contraseña la usa tanto Postgres (al crear el rol) como el API (en
`DATABASE_URL`). Para BBDD ya creadas hay que cambiarla en ambos lados.

```bash
# 1. Cambiar la contraseña dentro de Postgres
docker compose ... exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB \
  -c "ALTER USER soc WITH PASSWORD '<nuevo-valor>';"

# 2. Actualizar POSTGRES_PASSWORD en .env

# 3. Reiniciar el API (Postgres puede seguir corriendo con el rol ya
#    actualizado)
docker compose ... up -d --force-recreate api
```

### 2.4 `GEMINI_API_KEY` (clave global)

Es la clave que se usa cuando el user no ha configurado una BYO key.

```bash
# 1. Rotar en https://aistudio.google.com/apikey (revoca la vieja DESPUÉS
#    de confirmar que la nueva funciona).

# 2. Actualizar GEMINI_API_KEY en .env

# 3. Reiniciar el API
docker compose ... up -d --force-recreate api

# 4. Verificar
curl -fsS https://tu-dominio.example/api/health
```

No afecta a los usuarios con BYO key — esos usan su propia clave.

---

## 3. Migraciones Alembic

Las migraciones viven en `apps/api/alembic/versions/` y se aplican
automáticamente al arrancar el API (`init_db()` corre
`alembic upgrade head`). En SQLite cae a `Base.metadata.create_all` (solo
para tests).

### 3.1 Crear una migración nueva

```bash
# Desde el host, contra el contenedor:
docker compose -f infra/docker-compose.prod.example.yml exec api \
  alembic revision --autogenerate -m "add foo column to users"

# O en local (apps/api con venv activo):
cd apps/api
alembic revision --autogenerate -m "add foo column to users"
```

⚠️ **Revisa SIEMPRE el archivo generado** antes de aplicarlo. Alembic
autogenerate no detecta:
- Renames de columnas (los ve como drop + add → pierde datos).
- Cambios de tipo no triviales (varchar → text, etc.).
- Constraints `CHECK` complejos.

### 3.2 Aplicar migraciones

Automático en arranque del API. Si quieres forzarlo manualmente:

```bash
docker compose ... exec api alembic upgrade head
```

### 3.3 Rollback

```bash
# Bajar una revisión
docker compose ... exec api alembic downgrade -1

# Volver a una revisión concreta
docker compose ... exec api alembic downgrade <revision_id>
```

Antes de hacer rollback en prod, **siempre** un `pg_dump` (ver §4.1).

---

## 4. Backup y recuperación

### 4.1 Postgres

Backup manual:

```bash
docker compose -f infra/docker-compose.prod.example.yml exec -T postgres \
  pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup_$(date +%F).sql
```

Restore (sobre BBDD vacía):

```bash
docker compose ... exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB \
  < backup_2026-05-06.sql
```

Estrategia recomendada en producción:

```bash
# /etc/cron.d/soc-copilot-backup — cron diario a las 03:00 UTC
0 3 * * * root cd /opt/soc-copilot && \
  docker compose -f infra/docker-compose.prod.example.yml exec -T postgres \
    pg_dump -U soc soc_copilot | gzip > /var/backups/soc/$(date +\%F).sql.gz && \
  find /var/backups/soc -mtime +30 -delete
```

Sube los `.sql.gz` a almacenamiento externo (S3, B2, Hetzner Storage Box)
con `rclone` o equivalente. Un backup que vive solo en el VPS no es un
backup.

### 4.2 Chroma (vector store)

Los datos se persisten en el volumen `chroma-data`. Para backup:

```bash
docker run --rm -v soc-copilot-prod_chroma-data:/data \
  -v $(pwd):/backup alpine \
  tar czf /backup/chroma_$(date +%F).tar.gz -C /data .
```

Si el volumen se corrompe, **es mucho más simple re-ejecutar la ingesta
del KB** (§1.6) que restaurar el tar. La KB es derivada de fuentes
públicas (MITRE + OWASP) — no hay datos de usuario en Chroma.

---

## 5. Onboarding de un usuario

### 5.1 Vía panel admin (recomendado)

```
POST /api/admin/users
{
  "email": "analista@empresa.com",
  "password": "<temporal-fuerte>",
  "name": "Nombre Apellido",
  "role": "ANALYST"
}
```

UI: `/admin/users` → Nuevo usuario.

El admin entrega la contraseña temporal por canal seguro; el usuario
puede cambiarla después en `/settings`.

### 5.2 Vía registro público

Solo si `ALLOW_PUBLIC_REGISTRATION=true`. Útil durante el bootstrap o en
demos; en producción se mantiene en `false`.

---

## 6. Troubleshooting

| Síntoma | Causa probable | Acción |
|---------|---------------|--------|
| `Chat devuelve 502 "AI provider error"` | `GEMINI_API_KEY` inválida o cuota agotada | Verificar key en Google AI Studio; rotar (§2.4) |
| `User bloqueado por cuota servidor (429)` | Pasó del `SERVER_LLM_DAILY_QUOTA` diario | Admin: `POST /api/admin/users/{id}/reset-llm-quota`. O el user configura su BYO key en `/settings/llm` |
| `No puedo iniciar sesión tras rotar JWT_SECRET` | Comportamiento esperado | Hacer login de nuevo |
| `API no arranca: 'Refusing to start with insecure configuration'` | `APP_ENV=production` con secretos por defecto | Generar secretos reales (§1.3) y reiniciar |
| `Tests e2e fallan localmente` | Necesitan Postgres + `RUN_E2E=1` | Lanzarlos vía CI o `docker compose up postgres` antes |
| `BYO key del usuario "deja de funcionar"` tras un deploy | Probablemente se rotó `APP_ENCRYPTION_KEY` | El user vuelve a `/settings/llm` y la introduce de nuevo. Confirma en logs: `event=llm.byo_decrypt_failed` |
| `502 desde Caddy` | El API no está sano | `docker compose logs api`; revisar conexión a Postgres |
| `Migraciones no se aplican` | Versión de Alembic desincronizada | `docker compose exec api alembic current` y `alembic history` para diagnosticar |

### 6.1 Logs útiles

Todos los eventos del API se emiten en JSON estructurado en producción.
Ejemplos de filtros con `jq`:

```bash
# Logins fallidos del último deploy
docker compose logs api | jq 'select(.event=="auth.login" and .success==false)'

# Llamadas LLM con latencia > 1s
docker compose logs api | jq 'select(.event=="llm.call" and .latency_ms>1000)'

# Acciones admin recientes
docker compose logs api | jq 'select(.event=="admin.action")'

# Quotas exhaustas
docker compose logs api | jq 'select(.event=="llm.quota_exceeded")'
```

Ver también la sección "Logs" del README para la lista completa de
eventos.
