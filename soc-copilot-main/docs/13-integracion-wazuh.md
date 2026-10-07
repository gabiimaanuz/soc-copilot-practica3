# 13 · Integración con Wazuh (SIEM) — Práctica 2, mejora #1

> Roadmap Práctica 2 · funcionalidad #1 «Integración directa con SIEM»
> (prioridad Alta). Sustituye Elastic/Splunk por **Wazuh**.
> Estado: implementada (fase 1 de 4). Ver [14-practica2.md](14-practica2.md).

## 1. Qué resuelve

Antes, el analista tenía que **copiar y pegar** cada alerta en el Alert
Explainer. Ahora las alertas de Wazuh llegan solas a una **cola de triage
compartida** (`/siem`), ya priorizadas con la información que Wazuh
conoce (nivel de regla, descripción, agente, técnicas MITRE), y el
analista lanza el análisis IA con un clic.

La ingesta **no llama al LLM**: una tormenta de alertas no consume la
cuota compartida de Gemini. La IA solo se usa cuando un analista pulsa
«Analizar con IA».

## 2. Arquitectura

```text
                ┌────────────────────── Wazuh ──────────────────────┐
                │  wazuh-manager ── integratord ── custom-soccopilot │──PUSH──┐
                │        │                                           │        │
                │  wazuh-indexer (OpenSearch, wazuh-alerts-*)        │◄─PULL─┐│
                └────────────────────────────────────────────────────┘       ││
                                                                              ││
 SOC Copilot API (FastAPI)                                                    ││
 ├─ POST /api/integrations/wazuh/webhook  ◄───────────────────────────────────┘│
 │     Bearer WAZUH_WEBHOOK_TOKEN · rate limit propio · máx 2 MB / 100 alertas  │
 ├─ POST /api/integrations/wazuh/pull     (admin) ──────────────────────────────┘
 ├─ poller opcional cada WAZUH_POLL_INTERVAL_SECONDS (lifespan)
 │
 └─ services/wazuh.ingest_alerts()
        normaliza → filtra nivel < WAZUH_MIN_RULE_LEVEL → deduplica
        (origin, external_id) → INSERT alerts (user_id = NULL, analyzed_at = NULL)

 Frontend /siem  → GET /api/alerts?origin=wazuh&pending=true  (auto-refresco 15 s)
                 → POST /api/alerts/{id}/analyze  → Alert Explainer → /respond
```

### Modelo de datos (migración `0005_wazuh_integration`)

Nuevas columnas en `alerts`:

| Columna | Tipo | Uso |
|---|---|---|
| `origin` | varchar(16), default `manual`, índice | `manual` (pegada) o `wazuh` |
| `external_id` | varchar(128) | id de la alerta en Wazuh (`1728123072.123456`) |
| `rule_level` | int | `rule.level` de Wazuh (0-15) |
| `agent_name` | varchar(255) | agente que generó la alerta |
| `event_at` | timestamptz | hora del evento en Wazuh |
| `analyzed_at` | timestamptz | cuándo corrió la IA; `NULL` = pendiente |

Restricción `UNIQUE (origin, external_id)` → una misma alerta que llegue
por push y por pull (o reintentos de integratord) se guarda una sola vez.
Las alertas antiguas se rellenan con `analyzed_at = created_at`.

### Mapeo nivel Wazuh → riesgo

| `rule.level` | Riesgo inicial |
|---|---|
| 0-6 | low |
| 7-9 | medium |
| 10-12 | high |
| 13-15 | critical |

Al analizar con IA, el riesgo/MITRE/resumen se sustituyen por el
resultado del Alert Explainer (si la IA no devuelve técnicas, se
conservan las de Wazuh).

### Visibilidad (RBAC)

Centralizada en `app/services/alert_access.py`:

- **admin**: todas las alertas.
- **analista**: sus alertas manuales + **toda la cola Wazuh**. Al
  analizar una alerta Wazuh queda asignada (`user_id`) a quien la
  analizó, pero sigue visible para el equipo.
- Endpoints `status` y `pull`: permiso nuevo `integrations.manage`
  (admin por defecto, editable en la matriz de permisos).

## 3. Configuración — modo PUSH (recomendado, tiempo real)

1. Genera el token y ponlo en el `.env` de SOC Copilot:

   ```bash
   echo "WAZUH_WEBHOOK_TOKEN=$(openssl rand -hex 32)" >> .env
   docker compose -f infra/docker-compose.yml --env-file .env up -d api
   ```

2. En el **Wazuh manager**, instala el script:

   ```bash
   sudo cp integrations/wazuh/custom-soccopilot.py /var/ossec/integrations/
   sudo chown root:wazuh /var/ossec/integrations/custom-soccopilot.py
   sudo chmod 750 /var/ossec/integrations/custom-soccopilot.py
   ```

3. Añade el bloque de [`integrations/wazuh/ossec-integration.xml`](../integrations/wazuh/ossec-integration.xml)
   dentro de `<ossec_config>` en `/var/ossec/etc/ossec.conf`, con tu URL y
   el mismo token en `<api_key>`. Reinicia: `sudo systemctl restart wazuh-manager`.

4. Verifica: `sudo tail -f /var/ossec/logs/integrations.log` y la página
   `/siem` (panel «Estado de la integración» → «Último push»).

El script usa solo la librería estándar de Python (corre con el
intérprete que trae Wazuh), reintenta 3 veces con backoff ante errores de
red/5xx/429 y no reintenta ante 4xx (token o payload incorrectos).

## 4. Configuración — modo PULL (Wazuh Indexer)

Útil para recuperar alertas que se perdieron con el push (API caída) o
cuando no se puede tocar el `ossec.conf`.

```dotenv
WAZUH_INDEXER_URL=https://<ip-indexer>:9200
WAZUH_INDEXER_USER=<usuario de solo lectura>
WAZUH_INDEXER_PASSWORD=<password>
WAZUH_INDEXER_CA_CERT=/certs/root-ca.pem   # montar en el contenedor api
WAZUH_POLL_INTERVAL_SECONDS=60             # 0 = solo botón manual
```

- Consulta `POST <index>/_search` con `timestamp >= cursor` y
  `rule.level >= WAZUH_MIN_RULE_LEVEL`, orden ascendente, lote de 200.
- El cursor se guarda en `app_settings.wazuh_pull_cursor`. La primera vez
  mira `WAZUH_PULL_INITIAL_LOOKBACK_MINUTES` (60) hacia atrás.
- Recomendado: crear en el indexer un usuario con rol de **solo lectura**
  sobre `wazuh-alerts-*` en vez de usar `admin`.
- `WAZUH_INDEXER_VERIFY_TLS=false` solo en laboratorio; en producción la
  API se niega a arrancar si la URL no es `https://`.

Botón manual: `/siem` → «Sincronizar ahora» (admin).

## 5. Demo sin Wazuh: simulador

`integrations/wazuh/wazuh_simulator.py` envía alertas con el formato real
de `alerts.json` (fuerza bruta SSH 5712, SQLi 31103, FIM 550, Sysmon
92213, ransomware, y una de nivel 5 que debe descartarse):

```bash
export WAZUH_WEBHOOK_TOKEN=<el del .env>
python integrations/wazuh/wazuh_simulator.py --count 10 --interval 2
# Probar deduplicación (mismos ids):
python integrations/wazuh/wazuh_simulator.py --seed 42 --count 5
python integrations/wazuh/wazuh_simulator.py --seed 42 --count 5   # → duplicates: 1 cada una
# Ver el JSON sin enviar:
python integrations/wazuh/wazuh_simulator.py --dry-run --count 2
```

Respuesta del webhook (202):

```json
{"received": 1, "created": 1, "duplicates": 0, "below_threshold": 0, "invalid": 0, "created_ids": [57]}
```

## 6. Endpoints

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/api/integrations/wazuh/webhook` | `Bearer WAZUH_WEBHOOK_TOKEN` | Acepta 1 alerta, lista, o `{"alerts":[…]}`. 202. |
| POST | `/api/integrations/wazuh/pull` | sesión + `integrations.manage` | Un ciclo de pull. 502 si el indexer falla. |
| GET | `/api/integrations/wazuh/status` | sesión + `integrations.manage` | Estado push/pull, contadores, último error. |
| GET | `/api/alerts?origin=wazuh&pending=true` | sesión | Cola de triage (filtros nuevos `origin`, `pending`). |
| POST | `/api/alerts/{id}/analyze` | sesión, rate limit LLM | Ejecuta el Alert Explainer sobre una alerta guardada. |

Códigos del webhook: `503` token no configurado · `401` token inválido ·
`400` JSON inválido · `413` >2 MB o >`WAZUH_WEBHOOK_MAX_BATCH` · `429` rate limit.

## 7. Seguridad

- Token comparado en tiempo constante (`hmac.compare_digest`); en
  producción se exige ≥32 caracteres.
- El webhook no usa la cookie de sesión → no es vector CSRF.
- Bucket de rate limit propio (`WAZUH_WEBHOOK_RATE_LIMIT`, 600/min/IP).
- El contenido de la alerta es **dato no confiable**: llega al LLM
  entre los delimitadores `BEGIN_UNTRUSTED_LOG/END_UNTRUSTED_LOG` del
  Alert Explainer (protección anti prompt-injection existente).
- Log almacenado truncado a 20 000 caracteres (límite del Explainer).
- Auditoría: `alert.analyze` e `integration.wazuh.pull`.

## 8. Tests

- `apps/api/tests/test_wazuh.py` (offline, CI): mapeo de niveles,
  normalización, hash estable sin id, filtrado de MITRE inválido,
  truncado, forma de la query, auth del webhook (503/401), formatos de
  payload, JSON inválido, lote excesivo, reglas de visibilidad.
- `apps/api/tests/test_e2e_wazuh.py` (Postgres, `RUN_E2E=1`): webhook →
  dedupe → filtro de nivel → analista ve la cola → análisis con LLM
  falso → sale de pendientes → `status` prohibido a analistas.

## 9. Limitaciones conocidas

- Con varios workers de uvicorn cada uno arrancaría su poller; la
  deduplicación evita duplicados pero se harían consultas repetidas. El
  despliegue actual usa un único proceso.
- Si en un intervalo llegan más de `WAZUH_PULL_BATCH_SIZE` alertas, el
  resto se recoge en el siguiente ciclo.
- La ruta `/siem` refresca cada 15 s por polling (no WebSocket).
- Verificado en sintaxis y lógica pura en el entorno de desarrollo; la
  suite completa (pytest + `alembic check` + `next build`) debe pasar en
  CI o en local antes de desplegar.
