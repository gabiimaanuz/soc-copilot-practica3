# Instalacion local

## Requisitos

- Windows 11, macOS o Linux.
- Docker Desktop con Docker Compose v2.
- Git.
- Una clave de Gemini creada en Google AI Studio: <https://aistudio.google.com/apikey>.
- Recomendado en Windows: WSL2 activo y virtualizacion habilitada en BIOS/UEFI.

No es necesario instalar Python, Node.js ni PostgreSQL en local si se usa
Docker. El stack levanta todo en contenedores.

## Puertos usados

| Servicio | URL local | Puerto host |
|----------|-----------|-------------|
| Frontend Next.js | <http://localhost:13500> | 13500 |
| API FastAPI | <http://localhost:8080> | 8080 |
| Swagger API | <http://localhost:8080/docs> | 8080 |
| PostgreSQL | localhost:55432 | 55432 |
| ChromaDB | <http://localhost:8001> | 8001 |

> Nota Windows: 5432 (Postgres por defecto) y 3000 (Next por defecto) suelen
> estar en el rango excluido por Hyper-V en Windows 11. Por eso usamos
> 55432 y 13500. Ver [Solucion de problemas](05-solucion-problemas.md).

## Pasos de instalacion

1. Clonar o descomprimir el proyecto:

   ```bash
   git clone https://github.com/f3l0X/soc-copilot.git
   cd soc-copilot
   ```

2. Crear el archivo de entorno a partir del ejemplo:

   ```bash
   cp .env.example .env
   ```

   En Windows PowerShell, si `cp` no esta disponible:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Editar `.env`:

   ```env
   GEMINI_API_KEY=tu_clave_de_gemini
   ```

   Para entorno local se pueden mantener el resto de valores por defecto.
   Las variables de auth y rate-limit están documentadas en `.env.example`
   y en [docs/security.md](security.md).

4. Levantar el stack:

   ```bash
   cd infra
   docker compose up --build -d
   ```

   La primera vez tarda ~3 min (descarga imágenes + instala deps).

5. Comprobar arranque:

   ```bash
   docker compose ps
   curl http://localhost:8080/api/health
   ```

   Resultado esperado: 4 servicios healthy + `{"status":"ok"}`.

   > Las migraciones de Alembic (incluidas la `0003_level_approval` y la
   > `0004_app_settings`) se aplican automáticamente durante el primer
   > arranque de la API. Si en un entorno ya existente añades una
   > migración nueva, fuérzala con
   > `docker compose exec api alembic upgrade head`.

6. (Una vez por entorno) Poblar la base de conocimiento RAG. Sin este paso
   el chat funciona pero sin contexto MITRE/OWASP:

   ```bash
   docker compose exec api python -m scripts.ingest_kb
   ```

   El script tarda 5–15 min según RPM disponibles del free tier de Gemini.
   Detalle completo en [docs/08-rag-ingestion.md](08-rag-ingestion.md).

7. Crear el usuario admin desde el frontend:

   - Abrir <http://localhost:13500>.
   - Te redirige a `/login`. Pulsar **«¿No tienes cuenta? Regístrate»**.
   - El primer email registrado queda como **admin**. Los siguientes son
     **analyst**. Detalle en [docs/security.md](security.md).

8. Abrir la aplicacion:

   - Frontend: <http://localhost:13500>
   - Alert Explainer: <http://localhost:13500/alerts>
   - Next Step Recommender: <http://localhost:13500/respond?alert_id=N>
   - Histórico: <http://localhost:13500/history>
   - Chat IA: <http://localhost:13500/chat>
   - API docs: <http://localhost:8080/docs>

## Comandos utiles

| Acción | Comando |
|--------|---------|
| Parar contenedores | `docker compose down` |
| Parar y borrar volumenes (DB + KB) | `docker compose down -v` |
| Reconstruir | `docker compose up --build -d` |
| Ver logs API en vivo | `docker compose logs -f api` |
| Ver logs frontend | `docker compose logs -f web` |
| Tests backend | `docker compose exec api pytest -q` |
| Lint backend | `docker compose exec api ruff check app tests` |
| Estado KB | `curl http://localhost:8080/api/kb/status` |

## Pruebas basicas (smoke manual)

1. Login con tu usuario en <http://localhost:13500/login>.
2. Ir a `/alerts`, usar uno de los ejemplos, pulsar **Analizar**.
3. Confirmar resumen + riesgo + técnicas MITRE + razonamiento.
4. Pulsar **Siguiente paso**: aparecen acciones recomendadas.
5. Abrir `/history`: la alerta queda persistida con tu user_id.
6. Abrir `/chat`, hacer una pregunta sobre alguna técnica MITRE: la
   respuesta debe citar IDs como `mitre:T1110` u `owasp:A03:2025`.

Si algo falla, ver [docs/05-solucion-problemas.md](05-solucion-problemas.md).
