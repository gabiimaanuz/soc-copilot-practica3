# Ingesta RAG (Chroma + MITRE + OWASP)

## Qué hay en la base de conocimiento

Una única colección Chroma llamada `soc_kb`, poblada con dos tipos de
documento:

| Origen | IDs | Cantidad | Origen |
|--------|-----|----------|--------|
| MITRE ATT&CK Enterprise (técnicas vigentes) | `mitre:T####` y `mitre:T####.###` | 697 | bundle STIX descargado en runtime desde `attack-stix-data` |
| OWASP Top 10 2025 (categorías) | `owasp:A##:2025` | 10 | hardcodeado en `apps/api/scripts/owasp_top10.py` |

Total: **707 documentos** en producción a fecha 18/05/2026. Embeddings
de 3072 dim generados con `gemini-embedding-001`. La cifra de MITRE
fluctúa entre `git pull`s del bundle upstream.

## Cuándo se ejecuta la ingestión

- **Una vez por entorno** (al levantar el stack la primera vez).
- **Tras `docker compose down -v`** (que borra el volumen `chroma-data`
  y vacía la colección).
- **Cuando MITRE actualiza** y queremos refrescar (con `--force`).

NO se ejecuta automáticamente al arrancar la API: gastaría cuota de
Gemini en cada restart sin valor.

## Comando

**Desarrollo local:**
```bash
cd "D:/Evolve/Proyecto Blue Team/soc-copilot/infra"
docker compose exec api python -m scripts.ingest_kb
```

**Producción (Hetzner):**
```bash
ssh soc@178.105.51.187
docker compose -f /opt/soc-copilot/infra/docker-compose.prod.yml \
  --env-file /opt/soc-copilot/.env exec api python -m scripts.ingest_kb
```

Tarda 5–15 min según RPM disponibles del free tier de Gemini.

> **Aviso:** la cuota DIARIA de embeddings en el free tier es estricta.
> Si encuentras `RESOURCE_EXHAUSTED` repetidos y persistentes, el script
> entra en backoff de 30→90s. Si la cuota diaria se agota, no hay forma
> de continuar hasta el reset (00:00 PT ≈ 09:00 hora España). En ese
> caso, ejecuta `--owasp-only --force` para tener al menos OWASP cargado
> y reintenta MITRE al día siguiente, o activa billing pay-as-you-go en
> Google AI Studio (~0,01 €/707 docs).

## Flags soportados

| Flag | Comportamiento |
|------|----------------|
| (sin flags) | Ingerir OWASP + MITRE. Idempotente: si ya hay docs en `soc_kb`, no hace nada. |
| `--force` | Re-ingerir incluso si ya hay docs. |
| `--owasp-only` | Saltar MITRE (rápido, ~10 docs). |
| `--mitre-only` | Saltar OWASP. Útil si OWASP ya está y se cayó MITRE. |

## Verificar resultado

```bash
curl http://localhost:8080/api/kb/status
```

Salida esperada (cifras pueden variar según versión del bundle STIX):

```json
{"total": 707, "mitre": 697, "owasp": 10, "unknown": 0}
```

Si `total` es 0, la ingestión no corrió o falló.

## Cómo funciona internamente

`apps/api/scripts/ingest_kb.py`:

1. Comprueba si la colección `soc_kb` ya tiene docs. Si los tiene y no
   hay `--force`, sale.
2. Carga OWASP del módulo `scripts.owasp_top10`.
3. Descarga el bundle STIX de MITRE Enterprise (`raw.githubusercontent.com`).
4. Filtra `attack-pattern` no revoked y no deprecated, extrae `T####`,
   `name`, `description`, `kill_chain_phases`.
5. Construye documentos: `text` con `id — name\nTactics: ...\ndescription`
   y `metadata` con `source`, `name`, `technique_id` o `tags`.
6. Embebe en lotes de 50 docs (`EMBED_BATCH`) con backoff exponencial
   (`embed_with_retry`, hasta 8 intentos, delay inicial 30s para
   sobrevivir al reset minutal del free tier).
7. Sleep de 1.5s entre lotes (`INTER_BATCH_SLEEP`) para no triggear
   RPM caps.
8. Upsert a Chroma en chunks de 200 docs.

## Errores comunes

### `429 RESOURCE_EXHAUSTED ... limit: 100, model: gemini-embedding-1.0`

Has agotado el RPM del free tier de embeddings. El script reintenta con
backoff. Si sigue fallando tras 8 intentos:

- Esperar el reset minutal y reanudar con `--force`.
- O reducir batch (`EMBED_BATCH = 20` en el script).

### `chromadb.errors.InvalidArgumentError: Expected collection name that contains 3-63 characters`

Solo si tocas `KB_COLLECTION` en `app/services/rag.py`. Mantenerlo entre
3 y 63 chars alfanumérico/underscore/hyphen.

### `Chroma unavailable`

Comprobar `docker compose ps chroma`. Reinicia con `docker compose restart
chroma`.

### MITRE STIX 404 / red caída

GitHub raw.githubusercontent.com puede tirar transitoriamente. Reintentar.
Si persiste, descargar manualmente el bundle de
<https://github.com/mitre-attack/attack-stix-data/blob/master/enterprise-attack/enterprise-attack.json>
y servirlo desde un mirror local (cambiar `MITRE_STIX_URL` en el script).

## Coste aproximado

Embedding de ~700 docs con `gemini-embedding-001`:

- Free tier: cubierto, suele exigir 2–3 ventanas de un minuto.
- Pago (Vertex/Gemini API): ~700 × 200 tokens medios ≈ 140k tokens
  embebidos. Con tarifa ~0.025 €/M tokens ≈ <0.01 €. Despreciable.

## Política de actualización

Phase 4: ingesta manual a demanda.

Phase 5+ (ideas):

- Schedule mensual con GitHub Actions: cron job que llame a un endpoint
  protegido por API key del worker, que dispare `ingest_kb --force`.
- Diff inteligente: comparar SHA del bundle STIX antes de re-embeber.
- Soporte para fuentes custom (runbooks internos, normas, etc.).

## Mejoras pendientes (heredadas del audit fase 4)

- `--dry-run`: validar Chroma + parsear MITRE sin llamar a Gemini ni
  escribir.
- `--sample`: ingerir solo 10–20 docs locales sin red, útil para
  probar `/chat` offline en CI o entornos sin acceso a Gemini.

Estas mejoras no son bloqueantes. Aplazadas a iteración futura.

## Buscar en la KB sin pasar por el chat

Para inspeccionar qué hay realmente en Chroma:

```bash
docker compose exec api python -c "
from app.services.rag import get_collection
c = get_collection()
print('count:', c.count())
sample = c.get(limit=3, include=['documents','metadatas'])
for i, doc in enumerate(sample['documents']):
    print(f'--- {sample[\"ids\"][i]} ({sample[\"metadatas\"][i].get(\"source\")}) ---')
    print(doc[:200])
"
```
