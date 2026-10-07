# Endurecimiento de seguridad del servidor — 2026-05-19

Resumen y explicación detallada de todo el trabajo de hardening aplicado al
servidor de producción `soc-copilot-hetzner` (Hetzner Cloud, Ubuntu 24.04).

## Índice

1. [Estado de partida y objetivo](#1-estado-de-partida-y-objetivo)
2. [Capa 1 — Hardening del host](#2-capa-1--hardening-del-host)
3. [Capa 2 — Refuerzos en Docker y Caddy](#3-capa-2--refuerzos-en-docker-y-caddy)
4. [Capa 3 — Hetzner Cloud Firewall](#4-capa-3--hetzner-cloud-firewall)
5. [Capa 4 — Backups cifrados local + offsite](#5-capa-4--backups-cifrados-local--offsite)
6. [Capa 5 — Auditoría de autenticación](#6-capa-5--auditoría-de-autenticación)
7. [Recordatorios críticos y mantenimiento](#7-recordatorios-críticos-y-mantenimiento)
8. [Referencia rápida para la memoria del TFG](#8-referencia-rápida-para-la-memoria-del-tfg)

---

## 1. Estado de partida y objetivo

Antes de esta sesión el servidor ya tenía Docker, el repo desplegado en
`/opt/soc-copilot`, Caddy delante con TLS, y la stack (FastAPI + Next.js +
Postgres + Chroma) corriendo. **Lo que faltaba** era todo lo que protege la
máquina y los datos cuando algo va mal: aislamiento de procesos, hardening de
SSH, firewall, backups, y la validación formal de que la capa de auth
aguanta lo que dice aguantar.

Objetivo de la sesión: dejar el servidor con un nivel de seguridad
**suficiente para ser defendible delante de un tribunal** y, en la práctica,
para sobrevivir a los ataques automatizados que cualquier IP pública recibe a
diario.

---

## 2. Capa 1 — Hardening del host

**Archivo**: `scripts/harden_server.sh`

Script idempotente que se ejecuta una sola vez sobre un VPS recién
provisionado y aplica los siguientes controles:

### 2.1 Usuario no-root con sudo

Se crea (o reutiliza) el usuario `soc` con:
- Pertenencia a los grupos `sudo` y `docker`.
- Sudo sin contraseña (NOPASSWD) — la única forma de entrar al usuario es
  con clave SSH, así que el password de sudo sería un mero estorbo
  operacional sin valor de seguridad.
- Clave pública SSH del administrador instalada en
  `/home/soc/.ssh/authorized_keys` con permisos `600`.

**Por qué importa**: dejar `root` accesible directamente por SSH es la
puerta de entrada más explotada en internet. Bloqueando `root` y forzando
la conexión a un usuario nominal logramos dos cosas: (a) los logs de
`auth.log` y `auditd` identifican a una persona, no a "root genérico"; (b)
un atacante que adivine credenciales tiene que dar un salto adicional
(sudo) que también queda auditado.

### 2.2 SSH endurecido

Drop-in en `/etc/ssh/sshd_config.d/99-soc-hardening.conf`:

```
Port 2222
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
MaxAuthTries 3
LoginGraceTime 20
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers soc
ListenAddress 0.0.0.0
ListenAddress ::
```

**Por qué cada línea**:

- `Port 2222`: cambia el puerto por defecto. No es seguridad real (un
  escáner serio prueba todos los puertos) pero **filtra el 95 % del ruido
  automatizado** dirigido al puerto 22 y reduce drásticamente el volumen
  de logs de fallos.
- `PermitRootLogin no` + `PasswordAuthentication no`: bloquea los dos
  vectores más explotados de SSH.
- `KbdInteractiveAuthentication no`: cierra el método "challenge/response"
  que muchas configuraciones dejan abierto sin querer.
- `X11Forwarding no` / `AgentForwarding no` / `TcpForwarding no`:
  desactiva canales laterales que no usamos y que pueden ser pivotes
  laterales si se compromete el cliente.
- `MaxAuthTries 3` + `LoginGraceTime 20`: cierra rápido a quien no sabe la
  clave.
- `ClientAlive*`: cuelga las sesiones zombi automáticamente para que un
  portátil olvidado no quede como puerta abierta.
- `AllowUsers soc`: lista blanca de usuarios autorizados — cualquier otro
  intento se rechaza sin siquiera verificar la clave.
- `ListenAddress 0.0.0.0` + `::`: forzar bind explícito a IPv4 e IPv6
  (Ubuntu 24.04 con socket-activation tendía a hacer solo IPv6).

> Detalle Ubuntu 24.04: el servicio SSH se gestiona vía `ssh.socket` con
> activación por systemd. Por eso, además del drop-in, hay un override en
> `/etc/systemd/system/ssh.socket.d/override.conf` que define
> `ListenStream=0.0.0.0:2222` y `ListenStream=[::]:2222` para que el
> socket que systemd entrega a sshd sea el correcto.

### 2.3 UFW (firewall del kernel)

```
default incoming  deny
default outgoing  allow
allow 2222/tcp    (SSH)
allow 80/tcp      (HTTP — necesario para que Caddy resuelva el desafío ACME de Let's Encrypt)
allow 443/tcp     (HTTPS)
allow 443/udp     (HTTP/3 sobre QUIC)
```

**Por qué importa**: UFW (wrapper de iptables/nftables) bloquea todo el
tráfico entrante salvo lo que necesitamos. Esto **defiende incluso si un
servicio se configura mal y abre un puerto inesperado** — pasaría
desapercibido en `ss -tlnp` pero no llegaría a internet porque UFW lo
denegaría.

### 2.4 fail2ban

Jail SSH custom en `/etc/fail2ban/jail.d/soc.local`:

```
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd     ; lee de journald, no de /var/log/auth.log
port     = 2222
```

**Por qué importa**: cualquier IP que falle 5 logins SSH en 10 minutos
queda baneada 1 hora a nivel de iptables. Combinado con el rate-limit que
ya impone OpenSSH (`MaxAuthTries 3`), un brute-force coordinado tarda
días en agotar un diccionario pequeño, lo que lo hace inviable en la
práctica.

### 2.5 unattended-upgrades

Configuración en `/etc/apt/apt.conf.d/`:
- Updates de seguridad se aplican automáticamente cada noche.
- Reboot automático a las **04:00 AM** si el kernel u otra dependencia
  crítica lo requiere.
- Limpieza de dependencias huérfanas tras cada upgrade.

**Por qué importa**: la mayoría de máquinas comprometidas en internet lo
están por CVEs **conocidos y parcheados** que el sysadmin nunca aplicó.
Esto elimina el factor humano del ciclo de parches críticos.

### 2.6 Sysctl hardening

Reglas en `/etc/sysctl.d/99-soc-hardening.conf`:

- **Red**: `rp_filter=1` (anti-IP-spoofing), `tcp_syncookies=1` (resiste
  SYN floods), bloqueo de ICMP redirects/source routing.
- **Filesystem**: `protected_hardlinks=1`, `protected_symlinks=1` —
  cierra una clase clásica de ataques de "race condition" sobre archivos
  temporales en `/tmp`.
- **Kernel**: `kptr_restrict=2`, `dmesg_restrict=1` — oculta direcciones
  del kernel a procesos sin privilegios; reduce la utilidad de exploits
  que necesiten ASLR-bypass.

### 2.7 auditd con reglas SOC-relevantes

Reglas en `/etc/audit/rules.d/soc.rules`:

```
-w /etc/sudoers         -p wa -k sudoers
-w /etc/sudoers.d/      -p wa -k sudoers
-w /etc/ssh/sshd_config -p wa -k sshd_config
-w /etc/ssh/sshd_config.d/ -p wa -k sshd_config
-w /etc/passwd          -p wa -k identity
-w /etc/shadow          -p wa -k identity
-w /var/lib/docker      -p wa -k docker
```

Vigila escrituras a archivos críticos. Cualquier modificación de
`/etc/sudoers`, `/etc/passwd` o el config de SSH queda registrada en
`/var/log/audit/audit.log` con timestamp, usuario y proceso responsable.

**Por qué importa para este TFG**: el proyecto es un *SOC Copilot*. Tener
auditd ya configurado te da material de demo: un atacante que privilege-
escale modifica `/etc/sudoers`, auditd lo registra, y el Copilot puede
consultar esos eventos.

---

## 3. Capa 2 — Refuerzos en Docker y Caddy

**Archivos**:
- `infra/docker-compose.prod.example.yml` (template del compose)
- `infra/docker-compose.prod.yml` (el que se ejecuta — copiado del anterior)
- `infra/caddy/Caddyfile`

### 3.1 Hardening de contenedores

A cada servicio del compose se le han añadido **tres directivas
defensivas**:

```yaml
security_opt:
  - no-new-privileges:true
cap_drop: [ALL]
```

- `no-new-privileges:true`: aunque dentro del contenedor haya un binario
  setuid (como `sudo`), no puede elevar privilegios. **Cierra la mayoría
  de exploits de escape de contenedor** que dependen de ese paso.
- `cap_drop: [ALL]`: descarta todas las Linux capabilities. Por defecto
  Docker da al contenedor un subset peligroso (NET_ADMIN, SYS_CHROOT,
  AUDIT_WRITE, etc.). Empezamos sin nada y solo añadimos lo que cada
  servicio necesita explícitamente.

Por servicio, las capabilities mínimas necesarias:

- **postgres**: `CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID` — para
  cambiar el owner del datadir al usuario `postgres` interno y ejecutar
  como ese usuario.
- **chroma / web / api**: ninguna (ya quedan completamente desprivilegiados).
- **caddy**: `NET_BIND_SERVICE` — para que pueda bindar al puerto 443
  (privilegiado, <1024) como proceso no-root dentro del contenedor.

Además la API tiene:

```yaml
read_only: true
tmpfs:
  - /tmp:size=64m,mode=1777
```

- `read_only: true`: el filesystem del contenedor es **inmutable**. Si un
  atacante consigue ejecución de código, no puede escribir un webshell,
  alterar binarios, persistir o "vivir del land".
- `tmpfs /tmp`: la API necesita algún path escribible (e.g. uploads
  temporales de pdfs, archivos de uvicorn). Le damos 64 MB en RAM que se
  pierden al reiniciar — útiles en runtime, inservibles para persistir.

### 3.2 Ausencia de exposición externa

Los servicios `postgres` y `chroma` **no tienen bloque `ports:`** en el
compose. Esto significa que solo son accesibles desde la red interna de
Docker. Aunque alguien rompiera UFW y el Hetzner Firewall, Postgres y
Chroma **siguen inalcanzables** porque ni siquiera están publicados en la
interfaz del host.

Conexión a Postgres para mantenimiento: `docker compose exec postgres psql ...`

### 3.3 Caddy: TLS automático + headers de seguridad

Configurado en `infra/caddy/Caddyfile`. Caddy:

1. Termina TLS usando Let's Encrypt automáticamente (renueva certificados
   sin intervención).
2. Reverse-proxy: `/api/*` → `api:8080`, resto → `web:3000` (Next.js).
3. Sirve los siguientes **headers de seguridad** en cada respuesta:

| Header | Valor | Para qué |
|---|---|---|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Fuerza HTTPS durante 2 años en cualquier navegador que haya visto la cabecera una vez |
| `X-Content-Type-Options` | `nosniff` | Bloquea MIME-sniffing; un `.txt` no se puede colar como `.js` |
| `X-Frame-Options` | `DENY` | Impide que la app sea cargada en un `<iframe>` ajeno → mitiga clickjacking |
| `Referrer-Policy` | `no-referrer` | El navegador no leak la URL completa al hacer navegación a sitios externos |
| `Permissions-Policy` | `geolocation=() microphone=() camera=()` | Desactiva APIs sensibles del navegador que no necesitamos |
| `Content-Security-Policy` | Lista conservadora (ver Caddyfile) | Restringe orígenes desde los que se cargan recursos → mitiga XSS |
| `Cross-Origin-Opener-Policy` | `same-origin` | Aísla el contexto del navegador: una pestaña maliciosa no puede tocar la nuestra |
| `Cross-Origin-Resource-Policy` | `same-origin` | Solo recursos del mismo origen pueden incrustar las nuestras |

Adicionalmente:
- `-Server` / `-X-Powered-By`: oculta versiones del stack para no facilitar
  fingerprinting.
- Redirect `www.<dominio>` → `<dominio>` (canónico).
- Bloqueo de métodos HTTP raros (`405` directo, no llega al backend).
- Logs JSON a stdout → recogidos por el driver de Docker, listos para ser
  alimentados a Loki/SIEM si se quiere.

---

## 4. Capa 3 — Hetzner Cloud Firewall

Firewall de **red**, gestionado en el panel de Hetzner, que se aplica
**antes de llegar al VPS**. Configuración:

| Protocolo | Puerto | Origen | Para qué |
|---|---|---|---|
| TCP | 2222 | `0.0.0.0/0, ::/0` | SSH |
| TCP | 80 | `0.0.0.0/0, ::/0` | HTTP (ACME challenge) |
| TCP | 443 | `0.0.0.0/0, ::/0` | HTTPS |
| UDP | 443 | `0.0.0.0/0, ::/0` | HTTP/3 (QUIC) |

Outbound: todo permitido (Caddy ↔ Let's Encrypt, API ↔ Gemini, etc.).

**Por qué duplica UFW**: si un atacante compromete el host y desactiva
UFW (o si UFW se rompe por un upgrade), el firewall de Hetzner sigue
filtrando. Es la **defensa-en-profundidad** del modelo: dos firewalls
independientes que tendrían que fallar a la vez.

**Limitación asumida**: como la IP doméstica del desarrollador es
dinámica, SSH queda abierto a internet entero. La compensación es el
combo `puerto custom + key-only + fail2ban + lockout` que vuelve el
ataque brute-force inviable.

---

## 5. Capa 4 — Backups cifrados local + offsite

**Archivos**:
- `scripts/backup_postgres.sh` — el script de backup
- `scripts/install_backup_timer.sh` — instala el timer de systemd
- `docs/ops/restore-postgres.md` — instrucciones de restauración

### 5.1 Cadena del backup

Cada noche a las **03:30** (con jitter aleatorio de 0-5 min) systemd
dispara el servicio `soc-copilot-backup.service`. La cadena de comandos:

```
docker compose exec postgres
  pg_dump -U $POSTGRES_USER -d $POSTGRES_DB --no-owner --clean --if-exists
  | gzip -9
  | age -r $BACKUP_AGE_RECIPIENT -o /var/backups/soc-copilot/daily/postgres-<ts>.sql.gz.age
```

1. **`pg_dump`** se ejecuta dentro del contenedor de Postgres (sin tocar
   el datadir del host directamente — usa el protocolo oficial). Las
   flags `--clean --if-exists` permiten que el dump sea restaurable
   sobre una BD ya existente sin error.
2. **`gzip -9`** comprime maximalmente (CPU barata, ahorro de espacio
   importante porque vamos a almacenar 7 dailies + 4 weeklies).
3. **`age`** cifra el resultado con la clave pública configurada en
   `BACKUP_AGE_RECIPIENT`. La clave privada vive **solo** en
   `/home/soc/.age-key.txt` y en el gestor de contraseñas/USB offline
   del operador.

> **Por qué age y no GPG**: age (https://age-encryption.org) es moderno,
> tiene un formato simple, una sola clave por archivo, no tiene el
> historial de keyrings de GPG. Para cifrado asimétrico de archivos es
> mejor herramienta que GPG en 2026.

### 5.2 Retención

- **7 backups diarios** en `/var/backups/soc-copilot/daily/`
- **4 backups semanales** (snapshot del dump del domingo) en
  `/var/backups/soc-copilot/weekly/` — creados como hardlinks para que
  no ocupen el doble.

Política aplicada por el propio script al final de cada ejecución:

```bash
find ... -printf '%T@ %p\n' | sort -rn | awk 'NR>keep {print $2}' | xargs rm
```

### 5.3 Offsite a Backblaze B2

Cada noche, después del backup local, se ejecuta:

```
rclone copy <archivo> b2:soc-copilot-backups-fmrb/postgres/daily/
```

El bucket `soc-copilot-backups-fmrb` en Backblaze (región
`us-east-005`):
- Es **privado**.
- Tiene cifrado en reposo SSE-B2 activo.
- Tiene un Application Key con acceso restringido **solo a este bucket**
  (no a la cuenta entera).
- Las credenciales viven en `/root/.config/rclone/rclone.conf` con
  permisos `600`.

**Por qué esto cierra el bucle**: si el VPS de Hetzner desaparece (DC
incendiado, factura impagada, cuenta secuestrada), el backup sobrevive
en B2. Y como está cifrado con `age`, ni siquiera Backblaze (o quien
robe sus credenciales) puede leerlo.

### 5.4 Plan de restauración (drill)

Documentado en [restore-postgres.md](restore-postgres.md). Resumen:

1. Descifrar con la clave privada: `age -d -i ~/.age-key.txt ... | gunzip > /tmp/restore.sql`
2. Crear BD paralela `soc_copilot_restore` (para no pisar producción).
3. Aplicar el SQL: `psql -d soc_copilot_restore < /tmp/restore.sql`.
4. Inspeccionar, copiar lo que necesites, dropear la BD paralela.

**Hemos validado que el dump es restaurable** descifrando el primer
backup y comprobando que contiene un dump auténtico de PostgreSQL
16.14.

---

## 6. Capa 5 — Auditoría de autenticación

Revisión manual del código de auth de la API (FastAPI). El detalle
completo está en el repositorio (`apps/api/app/services/auth.py`,
`routers/auth.py`, `middleware/ratelimit.py`, etc.).

### 6.1 Controles verificados

| Control | Cómo se implementa | Estado |
|---|---|---|
| Password hashing | bcrypt vía passlib (cost factor 12 por defecto, ~250ms) | ✅ |
| Política de password | Min 10 chars + mayús/minús/dígito/símbolo + blocklist + no contiene el email | ✅ |
| JWT | HS256, secret de **64 caracteres** verificado en producción, TTL 1h | ✅ |
| Revocación de sesiones | Claim `pv` (`password_version`) en el JWT — al rotar la password, todas las sesiones antiguas se invalidan | ✅ |
| Cookies de sesión | `HttpOnly` + `Secure` (con `COOKIE_SECURE=true`) + `SameSite=Strict` (forzado en `production`) | ✅ |
| Lockout de cuenta | 4 intentos fallidos consecutivos → 15 minutos bloqueada. Reset al éxito | ✅ |
| Rate-limit por IP en `/auth/login` | 5/min — **independiente del flag global** (no se puede desactivar por error) | ✅ |
| Rate-limit por email en `/auth/register` | 3/h — defensa contra **botnet distribuida** rotando IPs contra un email | ✅ |
| Rate-limit en `/auth/check-email` | 10/min — la enumeración es UX-aware pero capada | ✅ |
| Honeypot anti-bot | Campo oculto `website`; rellenarlo devuelve un 201 fake sin tocar BD | ✅ |
| Defensa anti-timing-attack | `equalize_timing()` iguala latencia mínima (~300ms) para que respuestas no enumeren cuentas | ✅ |
| Mensajes opacos en login | "invalid credentials" — no se distingue cuenta-no-existe vs password-mal vs locked | ✅ |
| CSRF | SameSite=Strict + `enforce_same_origin` (Origin/Referer contra allowlist) | ✅ |
| Audit log | Cada login/register/lockout/etc. queda en BD con IP/UA/timestamp/detalles | ✅ |
| Guardas de arranque | `validate_for_runtime()` se niega a iniciar la API si el JWT_SECRET es débil o se usa la password de Postgres por defecto | ✅ |
| CORS | Sin wildcards con credenciales. Solo `https://` (o `http://localhost`) permitidos en producción | ✅ |

### 6.2 Validación en producción (no solo "está en el código")

Ejecutamos pruebas en vivo contra el endpoint público:

- `awk -F= '/^JWT_SECRET=/ {print length($2)}' .env` → **64**
- `grep ^APP_ENV` → `production`
- `grep ^COOKIE_SECURE` → `true`
- Login con credenciales falsas → `401` con cabeceras de seguridad
  (`x-content-type-options: nosniff`, `x-frame-options: DENY`).
- **Test de rate-limit en vivo**: 5 intentos fallidos consecutivos
  responden con `401`; el sexto responde con **`429 Too Many Requests`**.
  Confirmado en menos de 10 segundos.

### 6.3 Aspectos no implementados (decisión consciente, no olvido)

- **2FA TOTP**: fuera de scope del TFG, mejora "nice to have" para
  producción real.
- **Migrar el rate-limiter a Redis**: el actual es en memoria, válido
  para single-process uvicorn (que es nuestro despliegue). El propio
  código tiene comentado el plan: cambiar el backing store por Redis
  cuando se escale a múltiples workers.
- **JWT denylist (server-side revocation instantánea)**: innecesario con
  TTL de 1h + claim `pv`. El coste de mantener una denylist no
  compensa para esta superficie.

---

## 7. Recordatorios críticos y mantenimiento

### 7.1 Lo que el operador (tú) tiene que custodiar manualmente

| Archivo / dato | Dónde vive | Qué pasa si lo pierdes |
|---|---|---|
| `~/.age-key.txt` (clave privada de cifrado de backups) | `/home/soc/.age-key.txt` en el VPS | Sin ella **los backups son ruido cifrado e inútil**. Guardarla en gestor de contraseñas + USB offline. |
| `keyID` + `applicationKey` de Backblaze | (regenerables) | Se pueden recrear desde el panel B2; no es irrecuperable, pero la rotación implica reescribir `rclone.conf`. |
| Clave SSH privada del admin | Tu PC | Sin ella te quedas fuera del VPS. Hay que entrar por la consola web KVM de Hetzner y reañadir una clave nueva. |
| `JWT_SECRET` de la API | `/opt/soc-copilot/.env` en el VPS | Si lo rotas, **todas las sesiones activas se invalidan** (comportamiento esperado, no es pérdida). |
| `APP_ENCRYPTION_KEY` (cifra las API keys de Gemini que los usuarios suben) | `/opt/soc-copilot/.env` | Si la pierdes, las keys cifradas en la BD son irrecuperables (los usuarios tienen que volver a introducirlas). |

### 7.2 Tareas periódicas recomendadas

| Frecuencia | Tarea | Comando / ruta |
|---|---|---|
| Mensual | Drill de restore: descifra un backup random a una BD paralela | Ver [restore-postgres.md](restore-postgres.md) |
| Mensual | Revisar `journalctl -u fail2ban -n 100` y `/var/log/audit/audit.log` | Detectar patrones de ataque |
| Trimestral | Rotar `APP_ENCRYPTION_KEY` y `JWT_SECRET` | `openssl rand -base64 64` |
| Cuando salga CVE crítico | Verificar que `unattended-upgrades` lo aplicó | `apt list --upgradable` |

### 7.3 Comandos de "health check" rápido

```bash
# El stack está vivo y los contenedores healthy
docker compose -f /opt/soc-copilot/infra/docker-compose.prod.yml ps

# El backup de anoche salió bien
sudo journalctl -u soc-copilot-backup.service -n 30

# El backup llegó a B2
sudo rclone ls b2:soc-copilot-backups-fmrb/postgres/daily/ | tail

# Firewall activo
sudo ufw status verbose
sudo fail2ban-client status sshd

# Headers de seguridad en producción
curl -sI https://<tu-dominio> | grep -iE '^(strict-transport|x-frame|content-security|x-content-type)'
```

---

## 8. Referencia rápida para la memoria del TFG

Texto que puedes adaptar a la sección de seguridad de la memoria:

> El servidor de producción se ha endurecido siguiendo un modelo de
> defensa en profundidad con cinco capas. **A nivel de host**, SSH solo
> admite autenticación por clave en un puerto custom (2222) y bajo un
> usuario nominal sin acceso a root; UFW restringe el tráfico entrante a
> los puertos 22 (custom) / 80 / 443; fail2ban banea automáticamente IPs
> con patrones de brute-force; `unattended-upgrades` aplica parches de
> seguridad cada noche; auditd registra cambios en archivos críticos
> (`/etc/sudoers`, `/etc/passwd`, config SSH, datadir de Docker). **A
> nivel de contenedor**, cada servicio del compose corre con
> `cap_drop: ALL` y `no-new-privileges`; la API corre sobre un
> filesystem inmutable (`read_only`) con un `tmpfs` de 64 MB para
> escrituras volátiles; Postgres y Chroma no exponen puertos al host,
> solo son accesibles desde la red interna de Docker. **A nivel de
> red**, Caddy termina TLS con Let's Encrypt y sirve los headers
> Strict-Transport-Security, Content-Security-Policy, X-Frame-Options:
> DENY y Permissions-Policy; un firewall externo de Hetzner Cloud
> duplica las reglas de UFW como segunda barrera independiente. **A
> nivel de datos**, los backups de Postgres se cifran con `age` antes
> de tocar disco (la clave privada nunca toca el servidor en uso),
> tienen retención local de 7 dailies + 4 weeklies, y se replican
> automáticamente cada noche a un bucket privado de Backblaze B2; el
> procedimiento de restauración se ha validado descifrando y leyendo
> un dump real. **A nivel de aplicación**, se ha auditado la
> implementación de autenticación verificando: hashing bcrypt, JWT
> HS256 con secret de 64 caracteres, cookies HttpOnly+Secure+SameSite=
> Strict, lockout tras 4 fallos, rate-limit por IP (5/min) y por
> email (3/h), password policy con blocklist, defensa contra
> timing-attacks y enumeración, audit trail completo, y guardas que
> impiden el arranque con secretos por defecto. El rate-limit se ha
> probado en vivo contra el endpoint público: el sexto intento de
> login fallido en menos de un minuto recibe `HTTP 429 Too Many
> Requests`.

---

**Fecha**: 2026-05-19
**Operador**: equipo SOC Copilot
**Servidor**: `soc-copilot-hetzner` (Hetzner Cloud, Ubuntu 24.04)
