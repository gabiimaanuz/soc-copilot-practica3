# 🚀 Guía de arranque — SOC Copilot (Práctica 2)

> Sigue los pasos **en orden** y el proyecto arranca a la primera, con
> todo lo de la Práctica 2: Wazuh, informe PDF, idioma ES/EN, MFA,
> «¿Has olvidado tu contraseña?» y la nueva paleta de colores.
>
> Al final hay una **tabla con todos los problemas** que ya nos han pasado
> y cómo se arreglan. Si algo falla, búscalo ahí antes de tocar nada.
>
> Los comandos están pensados para **Windows + PowerShell** (la terminal de
> VS Code). En macOS o Linux son iguales, salvo cambiar `\` por `/`.

---

## Índice

- ★ [Lo que nos pasó de verdad (léelo primero)](#-lo-que-nos-pasó-de-verdad-léelo-primero)

0. [Lo que necesitas instalado](#0-lo-que-necesitas-instalado)
1. [Descomprimir y abrir el proyecto](#1-descomprimir-y-abrir-el-proyecto)
2. [Revisar el archivo `.env`](#2-revisar-el-archivo-env)
3. [Arrancar con Docker](#3-arrancar-con-docker)
4. [Primer acceso: crear el admin y activar el MFA](#4-primer-acceso-crear-el-admin-y-activar-el-mfa)
5. [Cargar la base de conocimiento del chat (opcional)](#5-cargar-la-base-de-conocimiento-del-chat-opcional)
6. [Probar cada funcionalidad](#6-probar-cada-funcionalidad)
7. [Cuando cambies código: qué comando usar](#7-cuando-cambies-código-qué-comando-usar)
8. [⚠️ Problemas conocidos y soluciones](#8-️-problemas-conocidos-y-soluciones)
9. [Empezar de cero (borrar todo)](#9-empezar-de-cero-borrar-todo)
10. [Tests automáticos](#10-tests-automáticos)
11. [Antes de subir a producción](#11-antes-de-subir-a-producción)

---

## ★ Lo que nos pasó de verdad (léelo primero)

Estos son los fallos **reales** que tuvimos al arrancar la Práctica 2, con
el comando que usamos, el error que salió y cómo quedó resuelto. Los
cuatro primeros **ya están corregidos en este proyecto**, así que si
sigues la guía no deberían volver a salir.

### 1. La base de datos del proyecto antiguo (`0005_group_messages`)

**Qué pasó:** lanzamos `docker compose --env-file ../.env up -d --build`
y se reutilizó la base de datos del proyecto **anterior**, cuyos
contenedores se llamaban `soc-copilot-...`. Esa base tenía una migración
`0005_group_messages` que el proyecto nuevo no conoce, y la API fallaba
con un error del tipo `Can't locate revision identified by '0005_group_messages'`.

**Cómo se resolvió:** usar un nombre de proyecto propio para la Práctica 2:

```powershell
docker compose -p soc-copilot-p2 --env-file ../.env up -d --build
```

**✅ Ya corregido:** `infra/docker-compose.yml` lleva ahora
`name: soc-copilot-p2`, así que **todos los comandos de esta guía usan
ya ese proyecto**, aunque no escribas `-p`. Si te acostumbraste a poner
`-p soc-copilot-p2`, puedes seguir haciéndolo: es lo mismo.

> Para ver qué proyectos tienes levantados y desde qué carpeta:
> `docker compose ls`. Si aparece el viejo `soc-copilot`, páralo **sin
> borrar sus datos**: `docker compose -p soc-copilot down`.

### 2. Docker no podía usar el disco E

**Qué pasó:** con el proyecto en
`E:\Master Ciberseguridad e IA\Practica 3\...`, al levantarlo Postgres no
arrancaba con este error:

```text
mkdir /run/desktop/mnt/host/e: file exists
```

Es un fallo de **Docker Desktop en Windows** al montar archivos de un
disco externo o USB, sobre todo si se conectó después de abrir Docker. El
proyecto no tiene ningún problema.

**Cómo se resolvió:**

1. Cerrar Docker Desktop: clic derecho en la ballena junto al reloj →
   **Quit Docker Desktop**.
2. En PowerShell:

   ```powershell
   wsl --shutdown
   ```

3. Comprobar que el disco E: está conectado y volver a abrir Docker Desktop.
4. Cuando esté en verde, desde la carpeta `infra`:

   ```powershell
   docker compose -p soc-copilot-p2 --env-file ../.env up -d --build
   ```

**Si vuelve a pasar:** copia el proyecto a **C:**, por ejemplo a
`C:\Users\<tu-usuario>\Documents\soc-copilot`. Es lo más fiable con Docker
en Windows.

### 3. Los logs de la API «se apagaban» tras las migraciones

**Qué pasó:** en `logs api` salía la migración (`Running upgrade ...`) y
después nada más: ni `Application startup complete` ni los errores. La
API funcionaba (`healthy`), pero no se veía qué pasaba.

**✅ Ya corregido** en `apps/api/alembic/env.py`
(`fileConfig(..., disable_existing_loggers=False)`).

### 4. El modelo de Gemini

**Qué pasó:** en el `.env` se usaba un modelo `gemini-2.5-...` y lo
cambiamos a **`gemini-3.5-flash-lite`**. Además, la barra superior siempre
mostraba «gemini-2.5-pro» porque estaba escrito a mano en `AppShell.tsx`.

**✅ Ya corregido:** el `.env` trae
`GEMINI_CHAT_MODEL=gemini-3.5-flash-lite` y
`GEMINI_CHAT_MODELS_ALLOWLIST=gemini-3.5-flash-lite`, y la barra superior
muestra el modelo que se está usando de verdad.

### 5. Dos copias del proyecto

**Qué pasó:** los cambios de un día se hicieron en
`C:\Users\Usuario\Downloads\...` y al día siguiente se arrancó otra copia
en `E:\...`, a la que le faltaban esos cambios.

**Regla:** trabaja siempre en **una sola carpeta**. Si copias el proyecto,
copia la carpeta entera, incluido el `.env`. Con `docker compose ls`
ves desde qué carpeta está corriendo cada proyecto.

### 6. Cómo comprobamos que todo funcionaba

Estos son los comandos que usamos, desde `infra`:

```powershell
docker compose -p soc-copilot-p2 --env-file ../.env ps
docker compose -p soc-copilot-p2 --env-file ../.env logs --tail 20 api
```

Todo está bien si los **4 contenedores** (`api`, `chroma`, `postgres`,
`web`) salen **Up** y `api`, `postgres` y `web` además **(healthy)**. En
los logs debe aparecer `Application startup complete`. Así nos quedó:

```text
soc-copilot-p2-api-1        Up About a minute (healthy)   127.0.0.1:8080->8080/tcp
soc-copilot-p2-chroma-1     Up About a minute             127.0.0.1:8001->8000/tcp
soc-copilot-p2-postgres-1   Up About a minute (healthy)   127.0.0.1:55432->5432/tcp
soc-copilot-p2-web-1        Up About a minute (healthy)   127.0.0.1:13500->3000/tcp
```

Con la base de datos del día anterior, la API aplicó sola la migración
nueva (`Running upgrade 0006_mfa_totp -> 0007_password_reset`) y se
conservaron la cuenta y las alertas.

---

## 0. Lo que necesitas instalado

| Programa | Para qué | Cómo comprobarlo |
|---|---|---|
| **Docker Desktop** | Levanta la base de datos, la API y la web | Ábrelo: abajo a la izquierda debe poner **Engine running** |
| **Visual Studio Code** | Abrir el proyecto y la terminal | — |
| **Clave de Gemini** | La IA (análisis, chat, informes) | Se crea gratis en <https://aistudio.google.com/app/apikey> |
| **App de autenticación en el móvil** | El MFA es obligatorio | Google Authenticator, Microsoft Authenticator, Authy… |
| Node.js 20 o superior *(opcional)* | Solo para pasar los tests del frontend | `node -v` |

> No hace falta instalar Python, PostgreSQL ni Wazuh: todo corre dentro de
> Docker, y Wazuh se simula con un script incluido.

---

## 1. Descomprimir y abrir el proyecto

1. Clic derecho sobre el `.zip` → **Extraer todo…** → **Extraer**.
   📍 **Extráelo en el disco C:**, por ejemplo en
   `C:\Users\<tu-usuario>\Documents\`. En discos externos (E:, USB) Docker
   falla (ver ★ punto 2).
2. ⚠️ **Si tenías una versión anterior del proyecto, cámbiale el nombre**
   (por ejemplo `soc-copilot-VIEJO`) o bórrala. Uno de los fallos que
   tuvimos fue lanzar Docker desde la carpeta vieja y no ver ningún cambio.
3. Abre **VS Code** → **Archivo → Abrir carpeta…** → elige la carpeta
   `soc-copilot-main`, la que contiene `apps`, `docs`, `infra`,
   `integrations` y este archivo `GUIA-ARRANQUE.md`.
4. Abre la terminal: **Terminal → Nuevo terminal**.
5. Comprueba que estás en la carpeta correcta:

   ```powershell
   dir GUIA-ARRANQUE.md
   ```

   Si dice que no existe, no estás en la carpeta buena (vuelve al punto 3).

> 💡 Para leer esta guía con formato dentro de VS Code: abre el archivo y
> pulsa `Ctrl + Shift + V`.

---

## 2. Revisar el archivo `.env`

El `.env` (en la raíz del proyecto) **ya viene preparado** con todas las
variables nuevas. Tiene ya generadas `APP_ENCRYPTION_KEY`, que es
imprescindible para el MFA, y `WAZUH_WEBHOOK_TOKEN`.

También trae ya el modelo `gemini-3.5-flash-lite`, que es el que usamos.

**Solo tienes que cambiar una línea:**

1. Abre `.env` en VS Code.
2. Busca `GEMINI_API_KEY=` y pon tu clave de Gemini:

   ```dotenv
   GEMINI_API_KEY=AIzaSy...tu_clave...
   ```

3. Guarda (`Ctrl + S`).

> ❗ **Si ya tenías el proyecto funcionando con tu propio `.env`** y ya
> activaste el MFA, **conserva tu `APP_ENCRYPTION_KEY` antigua**. Copia tu
> valor encima del nuevo. Si cambia esa clave, los códigos MFA guardados no
> se pueden leer (ver problema **P7**).

<details>
<summary>Qué hace cada variable nueva del <code>.env</code> (por si te lo preguntan)</summary>

| Variable | Valor en local | Para qué |
|---|---|---|
| `APP_ENCRYPTION_KEY` | ya generada | Cifra los secretos del MFA y las claves Gemini de los usuarios |
| `MFA_REQUIRED` | `true` | MFA obligatorio para todos |
| `MFA_ISSUER` | `SOC Copilot` | Nombre que sale en la app del móvil |
| `PASSWORD_RESET_TTL_MINUTES` | `30` | Validez del enlace de «¿Has olvidado tu contraseña?» |
| `WAZUH_WEBHOOK_TOKEN` | ya generado | Contraseña con la que Wazuh (o el simulador) envía alertas |
| `WAZUH_MIN_RULE_LEVEL` | `7` | Alertas por debajo de este nivel se descartan |
| `WAZUH_INDEXER_*` | vacías | Modo *pull* contra un Wazuh real. Vacías = desactivado (normal) |
| `SMTP_*` | vacías | Envío de emails. Vacías = los enlaces se muestran en pantalla (solo en local) |
| `WEB_BASE_URL` | `http://localhost:13500` | Dirección que se usa en los enlaces de los emails |

</details>

---

## 3. Arrancar con Docker

> ⚠️ **Todos los comandos `docker compose` se lanzan desde la carpeta
> `infra`** y siempre con `--env-file ../.env`. Si no, Docker no encuentra
> la configuración.
>
> El proyecto Docker se llama **`soc-copilot-p2`** (ya viene en
> `docker-compose.yml`). Escribir `-p soc-copilot-p2` es opcional: da
> igual ponerlo o no.

1. Asegúrate de que **Docker Desktop está abierto** y pone *Engine running*.
2. En la terminal de VS Code:

   ```powershell
   cd infra
   docker compose --env-file ../.env up -d --build
   ```

   La primera vez tarda **5-10 minutos** porque descarga y construye todo.

3. Comprueba que los 4 servicios están en marcha:

   ```powershell
   docker compose --env-file ../.env ps
   ```

   Tienen que aparecer `soc-copilot-p2-postgres-1`, `-chroma-1`, `-api-1`
   y `-web-1` con estado **Up**. `web` puede tardar unos 30 s más en estar
   *(healthy)*. Si los nombres empiezan por `soc-copilot-` **sin `p2`**,
   estás en el proyecto viejo (ver ★ punto 1).

   Y en los logs de la API:

   ```powershell
   docker compose --env-file ../.env logs --tail 20 api
   ```

   debe aparecer **`Application startup complete`**.

4. Comprueba que la base de datos está actualizada:

   ```powershell
   docker compose --env-file ../.env exec api alembic current
   ```

   Debe terminar en **`0007_password_reset (head)`**. Las migraciones se
   aplican solas al arrancar la API.

5. Abre en el navegador: **<http://localhost:13500>**

| Dirección | Qué es |
|---|---|
| <http://localhost:13500> | La aplicación |
| <http://localhost:8080/docs> | Documentación interactiva de la API (Swagger) |
| <http://localhost:8080/api/health> | Debe responder `{"status":"ok"}` |

---

## 4. Primer acceso: crear el admin y activar el MFA

1. En <http://localhost:13500> pulsa **«¿No tienes cuenta? Regístrate»**.
   **El primer usuario que se registra es el administrador.**
2. Inicia sesión con ese email y contraseña.
3. Aparece **«Activa la verificación en dos pasos»** con un **código QR**:
   - Escanéalo con la app de autenticación del móvil.
   - Escribe el código de 6 dígitos que muestra la app → **Verificar**.
4. Salen **10 códigos de recuperación**. **Descárgalos o cópialos** (botón
   *Descargar .txt*): solo se muestran esta vez. Marca la casilla →
   **Continuar**.
5. A partir de ahora, cada inicio de sesión = **contraseña + código de 6 dígitos**.

> El resto del equipo se registra igual. Cada uno escanea su propio QR.

---

## 5. Cargar la base de conocimiento del chat (opcional)

Para que el **Chat IA** cite MITRE ATT&CK y OWASP hay que poblar la base
de conocimiento **una sola vez** (~5 min, usa cuota de Gemini):

```powershell
docker compose --env-file ../.env exec api python -m scripts.ingest_kb
```

Sin este paso el chat funciona, pero sin citas («KB no disponible»).

---

## 6. Probar cada funcionalidad

### 6.1 SIEM · Wazuh (alertas automáticas)

1. Envía alertas de prueba con el simulador. Ya no hace falta copiar el
   token, porque lo lee del `.env`:

   ```powershell
   docker compose --env-file ../.env exec api python integrations/wazuh/wazuh_simulator.py --count 8 --interval 1
   ```

   Cada línea debe terminar en `'created': 1`. Las de **nivel 5** salen con
   `'below_threshold': 1`: se descartan a propósito.
2. En la app, menú izquierdo → **SIEM · Wazuh**. En ≤15 s aparecen las
   alertas en *Pendientes*.
3. Pulsa **Analizar con IA** en una. Arriba sale el análisis y la fila pasa
   a *Analizadas*.
4. Prueba anti-duplicados: lanza **dos veces** el mismo comando con
   `--seed 42 --count 5`. La segunda vez todas salen `'duplicates': 1`.

> «Pull (Indexer) — desactivado» y el botón **Sincronizar ahora** en gris
> son **normales**: solo se activan con un Wazuh real (`WAZUH_INDEXER_URL`).

### 6.2 Informe de incidente en PDF

- **Desde el chat:** *Chat IA* → haz 2 preguntas → botón morado
  **⤓ Generar informe de incidente (PDF)** → se descarga en *Descargas*.
- **Desde una alerta:** *SIEM · Wazuh* → *Analizar con IA* →
  **Siguiente paso → recomendar acciones** → (opcional) *Recomendar
  acciones* → al final de la página, el mismo botón morado.

### 6.3 Idioma

- Con la interfaz en **ES**, pregunta en el chat en inglés («Is this a
  false positive? What should I check first?») → responde **en inglés**.
- Pulsa **EN** arriba a la derecha y analiza una alerta → sale en inglés.

### 6.4 ¿Has olvidado tu contraseña?

1. Cierra sesión (**Salir**).
2. En el login → **«¿Has olvidado tu contraseña?»** → escribe tu email →
   **Enviar enlace**.
3. Como en local no hay email configurado, sale un **recuadro amarillo
   con el enlace** («Modo desarrollo»). Ábrelo.
4. Elige la contraseña nueva → **Guardar contraseña** → inicia sesión con
   ella (el código MFA se sigue pidiendo).

### 6.5 Colores (modo claro / oscuro)

Botón **Oscuro / Claro** de la barra superior. Comprobación rápida: en modo
claro, la palabra **«Pendiente»** de la tabla SIEM debe verse **marrón
oscuro** (no amarillo claro) y, al pasar el ratón por una fila o un botón,
debe cambiar de tono.

---

## 7. Cuando cambies código: qué comando usar

Siempre desde `infra`:

| Has cambiado… | Comando |
|---|---|
| Algo en `apps/web/src/` (páginas, componentes) | Nada: se recarga solo. Si no, `Ctrl + F5` en el navegador |
| `apps/web/tailwind.config.ts`, `package.json` o el `Dockerfile` de la web | `docker compose --env-file ../.env up -d --build web` |
| Algo en `apps/api/app/` | Nada: la API se recarga sola |
| `apps/api/requirements.txt` o el `Dockerfile` de la API | `docker compose --env-file ../.env up -d --build api` |
| El archivo `.env` | `docker compose --env-file ../.env up -d --force-recreate api web` |
| `infra/docker-compose.yml` | `docker compose --env-file ../.env up -d` |
| No sé qué ha cambiado / algo raro | `docker compose --env-file ../.env up -d --build --force-recreate` |

---

## 8. ⚠️ Problemas conocidos y soluciones

Los marcados con ✅ **ya nos pasaron** durante la Práctica 2.

### Arranque y Docker

| # | Lo que ves | Por qué pasa | Solución |
|---|---|---|---|
| P0a ✅ | `mkdir /run/desktop/mnt/host/e: file exists` al levantar | Docker Desktop no puede montar el disco E: (externo/USB) | Quit Docker Desktop → `wsl --shutdown` → abrir Docker → volver a levantar. Si se repite, mover el proyecto a C: (★ punto 2) |
| P0b ✅ | `Can't locate revision identified by '0005_group_messages'` | Se está usando la base de datos del proyecto antiguo | Ya corregido (`name: soc-copilot-p2`). Si lo ves: `docker compose ls`, para el viejo con `docker compose -p soc-copilot down` y levanta este (★ punto 1) |
| P0c ✅ | En los logs de la API no aparece `Application startup complete` | Alembic apagaba los logs tras migrar | Ya corregido en `alembic/env.py` (★ punto 3) |
| P0d ✅ | Los cambios de ayer «han desaparecido» | Estás arrancando otra copia del proyecto | `docker compose ls` para ver la carpeta en uso; trabaja siempre en una sola (★ punto 5) |
| P1 | `error during connect` o `docker: command not found` | Docker Desktop está cerrado | Abre Docker Desktop y espera a *Engine running* |
| P2 | `no configuration file provided` o variables vacías | Lanzaste el comando fuera de `infra` o sin `--env-file ../.env` | `cd infra` y usa siempre `--env-file ../.env` |
| P3 ✅ | Has cambiado archivos **y en la web no cambia nada** | Docker se lanzó desde la **carpeta vieja**, o el contenedor no se recreó | Comprueba con `dir ..\GUIA-ARRANQUE.md` que estás en la carpeta nueva. Luego `docker compose --env-file ../.env up -d --build --force-recreate` y `Ctrl + F5` |
| P4 | `port is already allocated` (13500, 8080, 55432 u 8001) | Otro programa o un stack antiguo usa ese puerto | `docker ps` → para el contenedor viejo con `docker stop <id>`, o cierra el programa que lo usa |
| P5 | La API no arranca y en `docker compose logs api` sale `Refusing to start with insecure configuration` | Has puesto `APP_ENV=production` con claves de ejemplo o `MFA_REQUIRED=false` | En local deja `APP_ENV=development`. Para producción, ver la sección 11 |

### Inicio de sesión y MFA

| # | Lo que ves | Por qué pasa | Solución |
|---|---|---|---|
| P6 ✅ | Error **503** al mostrar el QR, o *«APP_ENCRYPTION_KEY is not configured»* | `APP_ENCRYPTION_KEY` vacía en `.env` | Ya viene rellena en el `.env` nuevo. Si la cambiaste: rellénala y `up -d --force-recreate api` |
| P7 | *«MFA secret unreadable (APP_ENCRYPTION_KEY changed?)»* | Activaste el MFA con una `APP_ENCRYPTION_KEY` y ahora hay otra distinta | Vuelve a poner la clave antigua, **o** resetea el MFA de ese usuario (comando abajo) |
| P8 | «Código incorrecto» con un código bueno | La hora del móvil o del PC no está sincronizada | Activa la **hora automática** en ambos y prueba otra vez |
| P9 | No deja entrar tras varios intentos | Tras **4 fallos** (contraseña o código) la cuenta se bloquea **15 min** | Espera 15 min o `docker compose --env-file ../.env restart api` |
| P10 | Error **429** al iniciar sesión | Más de 5 intentos por minuto desde tu IP | Espera 1 minuto |
| P11 | He perdido el móvil | — | Usa un **código de recuperación**, o que un admin pulse **Reset MFA** en *Admin → Usuarios* |
| P12 | **El admin** ha perdido el móvil y los códigos | Nadie puede pulsar *Reset MFA* | Ejecuta el comando de abajo con su email y vuelve a iniciar sesión (pedirá QR nuevo) |
| P13 | He olvidado la contraseña | — | Botón **«¿Has olvidado tu contraseña?»** en el login (ver 6.4) |

Comando para P7 y P12 (cambia el email):

```powershell
docker compose --env-file ../.env exec postgres psql -U soc -d soc_copilot -c "UPDATE users SET mfa_enabled=false, mfa_secret_ciphertext=NULL, mfa_recovery_codes=NULL, mfa_last_used_step=NULL WHERE email='tu@email.com';"
```

### Wazuh / SIEM

| # | Lo que ves | Por qué pasa | Solución |
|---|---|---|---|
| P14 ✅ | El simulador responde **HTTP 503** | `WAZUH_WEBHOOK_TOKEN` vacío o la API no se reinició tras ponerlo | Ya viene en el `.env` nuevo. Si lo cambias: `up -d --force-recreate api` |
| P15 ✅ | El simulador responde **HTTP 401** | El token enviado no coincide con el del `.env` | Usa el comando de la sección 6.1, que lee el token del `.env` automáticamente |
| P16 | `python: command not found` o `No such file` al lanzar el simulador | Lo has lanzado en tu PC (sin Python) o el contenedor es anterior | Usa el comando de la 6.1, que corre **dentro** de la API. Si dice *No such file*: `up -d --force-recreate api` |
| P17 ✅ | **Sincronizar ahora** en gris / *Pull desactivado* | No hay un Wazuh Indexer real configurado | Es lo esperado. Pasa el ratón por el botón para ver el motivo |
| P18 | La página SIEM está vacía pero el simulador dijo `created: 1` | Estás en el filtro *Analizadas* | Pulsa *Pendientes* o *Todas* |

### IA (Gemini)

| # | Lo que ves | Por qué pasa | Solución |
|---|---|---|---|
| P19 | Error **502 «AI provider error»** al analizar, en el chat o en el informe | `GEMINI_API_KEY` vacía, de ejemplo o inválida, **o el modelo no está disponible** | Pon tu clave real en `.env`. Comprueba que `GEMINI_CHAT_MODEL` y `GEMINI_CHAT_MODELS_ALLOWLIST` sean `gemini-3.5-flash-lite` (★ punto 4) y ejecuta `up -d --force-recreate api`. O cada usuario pone su clave en **Settings** |
| P20 | Error **429** / «Daily AI call quota exhausted» | Agotadas las 50 llamadas diarias por usuario con la clave compartida | Pon tu propia clave en **Settings**, o un admin pulsa *Reset cuota* en *Admin* |
| P21 | El chat dice «KB no disponible» | No se cargó la base de conocimiento | Sección 5 |
| P22 | El chat responde en el idioma «equivocado» | Mensajes muy cortos («ok», «hola») no permiten detectar el idioma | Escribe frases completas, o cambia ES/EN arriba a la derecha |

### Aspecto visual

| # | Lo que ves | Por qué pasa | Solución |
|---|---|---|---|
| P23 ✅ | En modo claro no se lee nada o el hover no se nota | Configuración de colores vieja dentro del contenedor | Ya corregido: el contenedor monta `tailwind.config.ts`. `up -d --force-recreate web` + `Ctrl + F5` |
| P24 ✅ | Todos los botones **«Analizar con IA» en gris** | Antes se deshabilitaban todos mientras uno analizaba | Ya corregido: solo se atenúa el de la fila que se está analizando |
| P25 | La web sigue con el aspecto antiguo | Caché del navegador | `Ctrl + F5`, o abre una ventana de incógnito |

### Email

| # | Lo que ves | Por qué pasa | Solución |
|---|---|---|---|
| P26 | No llega el email de «¿Has olvidado tu contraseña?» | En local no hay SMTP configurado | Usa el **enlace del recuadro amarillo** que sale en la propia página. Para emails reales, rellena `SMTP_*` (ver `docs/operations.md`) |
| P27 | El enlace dice «inválido o caducado» | Caduca a los 30 min y solo vale una vez | Pide uno nuevo desde «¿Has olvidado tu contraseña?» |

### Ver qué está fallando

```powershell
docker compose --env-file ../.env logs --tail 80 api
docker compose --env-file ../.env logs --tail 80 web
```

Copia lo que salga en rojo o con `ERROR` y pásaselo a quien esté
ayudando: casi siempre indica la causa exacta.

---

## 9. Empezar de cero (borrar todo)

> ⚠️ **Borra la base de datos completa**: usuarios, MFA y alertas.
> Solo si algo está muy roto o quieres una demo limpia.

```powershell
docker compose --env-file ../.env down -v
docker compose --env-file ../.env up -d --build
```

Después vuelve al paso 4: el primer usuario que se registre será el admin.

---

## 10. Tests automáticos

Desde `infra`:

```powershell
# Estilo y errores del backend → debe decir "All checks passed!"
docker compose --env-file ../.env exec api ruff check app tests

# Tests unitarios → al final "... passed" y ningún "failed"
docker compose --env-file ../.env exec api pytest -q

# Base de datos coherente con el código → "No new upgrade operations detected."
docker compose --env-file ../.env exec api alembic check
```

> ⚠️ Los **tests e2e borran todos los usuarios y alertas**. Hazlos al
> final y solo en local:
>
> ```powershell
> docker compose --env-file ../.env exec -e RUN_E2E=1 -e MFA_REQUIRED=false api pytest tests/test_e2e_wazuh.py tests/test_e2e_mfa.py tests/test_e2e_password_reset.py -v
> ```

Frontend (necesita Node 20+):

```powershell
cd ..\apps\web
npm ci
npm run lint
npm run build
```

---

## 11. Antes de subir a producción

Las claves del `.env` incluido son **solo para desarrollo local**. En el
servidor:

1. Genera claves nuevas **en el servidor**:

   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # APP_ENCRYPTION_KEY
   openssl rand -hex 32        # WAZUH_WEBHOOK_TOKEN
   openssl rand -base64 48     # JWT_SECRET
   ```

2. En el `.env` del servidor: `APP_ENV=production`, `MFA_REQUIRED=true`,
   `COOKIE_SECURE=true`, `API_CORS_ORIGINS=https://tu-dominio` y `SMTP_*`
   rellenos (para que lleguen los emails de recuperación).
3. Despliega como siempre (`docs/operations.md`). Las migraciones
   0005-0007 se aplican solas al arrancar la API.
4. **Avisa al equipo**: en su próximo inicio de sesión todos tendrán que
   escanear el QR del MFA. El admin primero.

---

### Más documentación

| Tema | Documento |
|---|---|
| Resumen de la Práctica 2 y lista de cambios | [docs/14-practica2.md](docs/14-practica2.md) |
| Wazuh (incluida la conexión con un Wazuh real) | [docs/13-integracion-wazuh.md](docs/13-integracion-wazuh.md) |
| Informe PDF | [docs/15-informe-incidente.md](docs/15-informe-incidente.md) |
| Idioma ES/EN | [docs/16-multiidioma.md](docs/16-multiidioma.md) |
| MFA | [docs/17-mfa-totp.md](docs/17-mfa-totp.md) |
| Colores | [docs/18-paleta-colores.md](docs/18-paleta-colores.md) |
| Recuperar contraseña | [docs/19-recuperar-contrasena.md](docs/19-recuperar-contrasena.md) |
| Manual de usuario | [docs/10-manual-usuario.md](docs/10-manual-usuario.md) |
