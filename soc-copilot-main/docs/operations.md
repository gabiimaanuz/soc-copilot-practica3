# SOC Copilot — Manual de operaciones

Servidor de producción: `soc@178.105.51.187` (Hetzner CPX22, Nuremberg)
URL pública: https://soc-copilot.duckdns.org
Stack: Postgres 16 · ChromaDB · FastAPI · Next.js · Caddy 2 (TLS auto)

---

## 1. Acceso al servidor

```bash
ssh soc@178.105.51.187
```

- Login root deshabilitado. Solo usuario `soc` con clave SSH.
- `soc` tiene `sudo` sin password (`NOPASSWD`).
- Si pierdes la clave: Hetzner Console → tu servidor → **Rescue** → **Reset root password**, luego entras por la **consola web** y reañades tu key en `~soc/.ssh/authorized_keys`.

El código vive en `/opt/soc-copilot`. Todos los comandos de operación se ejecutan desde ahí.

---

## 2. Desplegar una versión nueva

Cuando se haya mergeado a `main` en GitHub:

```bash
ssh soc@178.105.51.187
bash /opt/soc-copilot/scripts/deploy.sh
```

El script hace:
1. `git pull --ff-only`
2. Valida que `.env` tiene los secretos obligatorios
3. `docker compose ... up -d --build`
4. Muestra estado y últimos logs

Tarda 3–8 min según qué cambie. La app puede dar 502 durante los últimos 10–20s mientras Caddy reconecta a los contenedores nuevos.

### Pre-flight checklist (ejecutar SIEMPRE antes del deploy)

Antes de `bash scripts/deploy.sh`, verifica:

```bash
cd /opt/soc-copilot

# 1. ¿Hay cambios locales sin commitear en el server? (deben ser 0)
git status --short

# 2. ¿La rama está al día con remoto?
git fetch
git status -uno   # debe decir "Your branch is up to date with 'origin/main'"

# 3. ¿Hay migraciones nuevas en el repo que no estén aplicadas en BD?
diff <(ls apps/api/alembic/versions/ | sort) \
     <(docker compose -f infra/docker-compose.prod.yml --env-file .env \
         exec api ls alembic/versions/ 2>/dev/null | sort) || \
   echo "⚠️ Migraciones en repo != contenedor"
```

Si paso 1 muestra algún archivo modificado en el server, **NO hagas pull todavía**:
```bash
git diff <archivo>                       # mira qué cambió
git stash -u                              # guarda los cambios local
# o si son patches obsoletos ya en remoto:
git checkout -- <archivo>                 # descarta
```

### Migraciones de base de datos

Por defecto la API **no** corre `alembic upgrade head` al arrancar (solo aplica las que estaban presentes en el primer arranque). Después de cada deploy con migraciones nuevas, **fuerza la subida**:

```bash
cd /opt/soc-copilot/infra
docker compose -f docker-compose.prod.yml --env-file ../.env exec api alembic upgrade head
docker compose -f docker-compose.prod.yml --env-file ../.env exec api alembic current
```

`alembic current` debe terminar con `(head)`. Si dice `Running upgrade X -> Y` ya las aplicó. Si dice solo `0002_xxx (head)` cuando esperabas `0003_xxx`, la migración no llegó al contenedor — revisa que el `git pull` en el server haya ido bien y que el `--build` no haya usado caché stale (rebuild con `build --no-cache <servicio>`).

### Errores típicos y cómo evitarlos

- **`TypeError: 'X' is an invalid keyword argument for User`** en el endpoint de registro → falta aplicar una migración. Ejecuta `alembic upgrade head` y vuelve a probar.
- **El frontend muestra "Internal Server Error" en text/plain** pero la API responde 200 a `GET /` → un endpoint está reventando con excepción no manejada por la middleware ASGI. Captura el traceback con:
  ```bash
  docker compose -f docker-compose.prod.yml --env-file ../.env exec api python -c "
  import logging; logging.basicConfig(level=logging.DEBUG)
  from app.main import app
  from fastapi.testclient import TestClient
  c = TestClient(app)
  r = c.post('/api/<endpoint>', json={...})
  print(r.status_code, r.text)
  " 2>&1 | tail -60
  ```
  `TestClient` salta uvicorn y deja que las excepciones afloren tal cual.
- **`git pull` aborta con "Your local changes ... would be overwritten"** → algún patch manual quedó en el server fuera del repo. Compara con `git diff <archivo>`; si es equivalente a lo de upstream, `git checkout -- <archivo>` y vuelve a pullear.

---

## 3. Inspeccionar el stack

Atajo recomendado al entrar:

```bash
cd /opt/soc-copilot/infra
alias dc='docker compose -f docker-compose.prod.yml --env-file ../.env'
```

Operaciones comunes:

```bash
dc ps                          # estado de servicios
dc logs -f api                 # logs API en directo (Ctrl+C para salir)
dc logs --tail=200 caddy       # últimas 200 líneas de Caddy
dc logs --tail=50 web          # logs Next.js
dc exec api bash               # shell dentro del contenedor API
dc exec postgres psql -U soc -d soc_copilot   # consola SQL
dc restart api                 # reinicia solo la API
dc down && dc up -d            # apaga todo y vuelve a levantar (sin rebuild)
```

---

## 4. Gestión de usuarios

### Abrir o cerrar el registro público

**Desde el panel de administración (recomendado):**

Login como admin → **Administración** → toggle **"Registro público"**. El cambio es inmediato, no requiere reiniciar contenedores.

**Desde el servidor (fallback si la UI no es accesible):**

```bash
# Cerrar
cd /opt/soc-copilot
sed -i 's/ALLOW_PUBLIC_REGISTRATION=.*/ALLOW_PUBLIC_REGISTRATION=false/' .env
cd infra && dc up -d api

# Abrir (para que el grupo o el tribunal pueda probar el registro)
cd /opt/soc-copilot
sed -i 's/ALLOW_PUBLIC_REGISTRATION=.*/ALLOW_PUBLIC_REGISTRATION=true/' .env
cd infra && dc up -d api

# Verifica el estado actual
grep ALLOW_PUBLIC_REGISTRATION /opt/soc-copilot/.env
```

**Directo en la base de datos** (el override de la UI vive aquí):

```bash
# Ver estado actual
dc exec postgres psql -U soc -d soc_copilot -c \
  "SELECT key, value, updated_at FROM app_settings WHERE key='public_registration_enabled';"

# Forzar a abierto
dc exec postgres psql -U soc -d soc_copilot -c \
  "INSERT INTO app_settings(key, value) VALUES('public_registration_enabled','true')
   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now();"

# Forzar a cerrado
dc exec postgres psql -U soc -d soc_copilot -c \
  "INSERT INTO app_settings(key, value) VALUES('public_registration_enabled','false')
   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now();"
```

Precedencia: si `app_settings.public_registration_enabled` existe, manda sobre `ALLOW_PUBLIC_REGISTRATION` del `.env`. Si no existe, se usa el `.env` como fallback. Esto permite tocar el flag sin redeploy.

> **Tip para demos al tribunal**: deja el flag en `false` por defecto y ábrelo solo durante la demo del flujo de registro. Cierra inmediatamente después.

### Promover a admin manualmente (sin esperar SMTP)

```bash
dc exec postgres psql -U soc -d soc_copilot -c \
  "UPDATE users SET role='admin', email_verified=true WHERE email='user@ejemplo.com';"
```

### Resetear el password de un usuario
Usa el panel admin de la app — un `UPDATE` directo en la tabla **no calcula el hash bcrypt** y el usuario no podrá entrar.

### Ver usuarios en la base
```bash
dc exec postgres psql -U soc -d soc_copilot -c \
  "SELECT id, email, role, email_verified, level FROM users ORDER BY id;"
```

---

## 5. Backups

### Postgres — dump diario automático

Instala una vez:
```bash
sudo tee /etc/cron.daily/soc-copilot-pgbackup > /dev/null <<'CRON'
#!/bin/bash
set -e
BACKUP_DIR=/var/backups/soc-copilot
mkdir -p "$BACKUP_DIR"
cd /opt/soc-copilot/infra
docker compose -f docker-compose.prod.yml --env-file ../.env exec -T postgres \
  pg_dump -U soc -d soc_copilot --clean --if-exists \
  | gzip > "$BACKUP_DIR/db-$(date +%Y%m%d).sql.gz"
find "$BACKUP_DIR" -name "db-*.sql.gz" -mtime +14 -delete
CRON
sudo chmod +x /etc/cron.daily/soc-copilot-pgbackup
```

Guarda 14 días. Verifica que corre:
```bash
sudo run-parts --test /etc/cron.daily
ls -lh /var/backups/soc-copilot/
```

### Dump manual a tu home
```bash
cd /opt/soc-copilot/infra
dc exec -T postgres pg_dump -U soc -d soc_copilot --clean --if-exists \
  | gzip > ~/db-manual-$(date +%Y%m%d-%H%M).sql.gz
```

### Restaurar un dump
```bash
gunzip -c /ruta/al/db-YYYYMMDD.sql.gz | \
  dc exec -T postgres psql -U soc -d soc_copilot
```

### Snapshots Hetzner
Diarios, retenidos 7 días. Restauración desde Hetzner Console → tu servidor → **Backups**. Estos son a nivel disco; el dump SQL es portable a otra máquina.

### `.env` (secretos)
**No está en git** (a propósito). Cópialo a tu Windows como respaldo offline:
```powershell
scp soc@178.105.51.187:/opt/soc-copilot/.env $env:USERPROFILE\Documents\soc-copilot-env-backup\env-$(Get-Date -Format "yyyyMMdd").bak
```

---

## 6. Seguridad

### Firewall (UFW)
Solo 22, 80, 443 abiertos. Estado:
```bash
sudo ufw status verbose
```

### fail2ban
Banea IPs con muchos fallos SSH. Estado:
```bash
sudo fail2ban-client status sshd
```

### SSH hardening aplicado (`/etc/ssh/sshd_config.d/99-hardening.conf`)
- `PermitRootLogin no`
- `PasswordAuthentication no`
- `AllowUsers soc`
- Máximo 3 intentos por sesión

### Actualizaciones automáticas
`unattended-upgrades` aplica parches de seguridad solo. Reinicios manuales:
```bash
sudo apt update && sudo apt upgrade -y
sudo reboot   # solo si toca kernel
```

### Rotar secretos
- `JWT_SECRET`: cerrar sesiones activas. Edita `.env` y `dc up -d api`.
- `APP_ENCRYPTION_KEY`: **¡cuidado!** Invalida las claves Gemini cifradas por usuario. Cada usuario tendrá que volver a meter la suya.
- `POSTGRES_PASSWORD`: requiere `ALTER USER` en Postgres y actualizar `.env` simultáneamente.

---

## 7. Disco y recursos

```bash
df -h                  # espacio libre
free -h                # RAM + swap
docker system df       # qué ocupan imágenes/volúmenes/build cache
htop                   # CPU y procesos
```

Limpieza si el disco se llena (ojo, irreversible):
```bash
docker image prune -af        # imágenes no usadas
docker builder prune -af      # cache de buildkit
docker volume prune           # ⚠️ NO ejecutes esto sin revisar — borra volúmenes huérfanos
```

---

## 8. Troubleshooting

### "Failed to fetch" en login (o cualquier llamada a la API)
`NEXT_PUBLIC_API_URL` no quedó embebida en el bundle de Next.js. Verifica:
```bash
dc exec web sh -c "grep -ro 'soc-copilot.duckdns.org' .next/static/chunks/ | head -1"
```
Si vacío → rebuild forzado:
```bash
dc build --no-cache web && dc up -d web
```
Y en el navegador: F12 → Network → **Disable cache** + Ctrl+Shift+R.

### Caddy no consigue el certificado TLS
Comprueba que el dominio resuelve a la IP del servidor y que el puerto 80 está abierto:
```bash
dig +short soc-copilot.duckdns.org    # debe devolver 178.105.51.187
curl -I http://soc-copilot.duckdns.org
dc logs caddy | grep -iE "acme|certificate"
```
Si DuckDNS apunta a otra IP, ve a https://www.duckdns.org y actualiza.

### La API no arranca
```bash
dc logs api | tail -80
```
Causa más común: variable obligatoria ausente o inválida en `.env` (la API en `APP_ENV=production` se niega a arrancar con secretos por defecto).

### Postgres no acepta conexiones
```bash
dc ps postgres                     # ¿healthy?
dc logs postgres | tail -40
dc exec postgres pg_isready -U soc -d soc_copilot
```

### Sesiones no persisten / cookies se pierden
- Verifica `COOKIE_SECURE=true` y que entras por **https** (no http).
- Verifica que `NEXTAUTH_URL=https://soc-copilot.duckdns.org` (sin trailing slash).

### El navegador muestra contenido antiguo
Cache. F12 → Network → Disable cache → Ctrl+Shift+R. Si persiste, modo incógnito.

---

## 9. Contactos y responsables

- **Owner técnico**: fmruibal91@gmail.com
- **Email Let's Encrypt**: el mismo (sale en `ACME_EMAIL` del `.env`)
- **Repo**: https://github.com/f3l0X/soc-copilot (privado)
- **Hetzner Console**: https://console.hetzner.cloud — solo el owner
- **DuckDNS**: https://www.duckdns.org — token compartido por el owner

---

## 10. Checklist de salud (mensual, 5 min)

```bash
# 1. Servicios arriba
dc ps

# 2. Disco bajo control
df -h /

# 3. Últimos backups existen
ls -lh /var/backups/soc-copilot/ | tail -5

# 4. Cert TLS vigente (>30 días)
echo | openssl s_client -connect soc-copilot.duckdns.org:443 -servername soc-copilot.duckdns.org 2>/dev/null \
  | openssl x509 -noout -dates

# 5. Sin intentos de intrusión raros
sudo fail2ban-client status sshd

# 6. Actualizaciones de seguridad pendientes
sudo apt list --upgradable 2>/dev/null | grep -i security
```

Si todo verde → estás bien un mes más.
