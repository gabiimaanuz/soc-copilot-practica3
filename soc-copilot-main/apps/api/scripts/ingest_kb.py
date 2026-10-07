"""Idempotent ingestion of MITRE ATT&CK + OWASP Top 10 into ChromaDB.

Run from inside the api container:
    docker compose exec api python -m scripts.ingest_kb            # full
    docker compose exec api python -m scripts.ingest_kb --force    # rebuild
    docker compose exec api python -m scripts.ingest_kb --owasp-only

Embeds in batches via Gemini (`text-embedding` family) and writes the docs
to the ``kb`` Chroma collection used by the /api/chat RAG service.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from collections.abc import Iterable
from typing import Any

from app.services.llm import GeminiAdapter
from app.services.rag import KB_COLLECTION, get_collection
from scripts.owasp_top10 import OWASP_TOP_10_2025

MITRE_STIX_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json"
)

EMBED_BATCH = 50  # Gemini accepts up to 100; 50 keeps us under daily quotas.
INGEST_BATCH = 200  # Chroma add() chunk size
INTER_BATCH_SLEEP = 1.5  # seconds between embed batches to ride free-tier RPM

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ingest_kb")


# ─── MITRE STIX ─────────────────────────────────────────────────────────────


def fetch_mitre_stix(url: str = MITRE_STIX_URL) -> dict[str, Any]:
    log.info("downloading MITRE STIX bundle from %s", url)
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def extract_mitre_techniques(stix: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obj in stix.get("objects", []):
        if obj.get("type") != "attack-pattern":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        ext_id = None
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack":
                ext_id = ref.get("external_id")
                break
        if not ext_id:
            continue
        name = obj.get("name", "")
        description = (obj.get("description") or "").strip()
        tactics = [
            p.get("phase_name", "")
            for p in obj.get("kill_chain_phases", [])
            if p.get("phase_name")
        ]
        out.append(
            {
                "id": ext_id,
                "name": name,
                "description": description,
                "tactics": tactics,
            }
        )
    return out


# ─── Embedding helpers ──────────────────────────────────────────────────────


def _chunked(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def embed_with_retry(
    llm: GeminiAdapter, texts: list[str], max_retries: int = 8
) -> list[list[float]]:
    """Retry embed with backoff that survives Gemini free-tier 429s.

    Free tier resets per-minute, so the first backoff is already long
    enough to outlast a window. Subsequent retries grow exponentially.
    """
    delay = 30.0
    for attempt in range(1, max_retries + 1):
        try:
            return llm.embed(texts)
        except Exception as exc:
            is_429 = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            if attempt == max_retries:
                raise
            log.warning(
                "embed attempt %d/%d failed (%s) — sleeping %.1fs",
                attempt,
                max_retries,
                "rate-limited" if is_429 else type(exc).__name__,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 1.5, 90.0)
    return []  # unreachable, keeps type checker happy


# ─── Ingestion main loop ────────────────────────────────────────────────────


def build_mitre_docs(techniques: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = []
    for t in techniques:
        text_parts = [f"{t['id']} — {t['name']}"]
        if t.get("tactics"):
            text_parts.append(f"Tactics: {', '.join(t['tactics'])}")
        if t.get("description"):
            text_parts.append(t["description"])
        docs.append(
            {
                "id": f"mitre:{t['id']}",
                "text": "\n".join(text_parts),
                "metadata": {
                    "source": "mitre",
                    "name": f"{t['id']} — {t['name']}",
                    "technique_id": t["id"],
                    "tactics": ",".join(t.get("tactics", [])),
                },
            }
        )
    return docs


def build_owasp_docs() -> list[dict[str, Any]]:
    return [
        {
            "id": f"owasp:{e['id']}",
            "text": f"{e['id']} — {e['name']}\n\n{e['description']}",
            "metadata": {
                "source": "owasp",
                "name": f"{e['id']} — {e['name']}",
                "tags": ",".join(e.get("tags", [])),
            },
        }
        for e in OWASP_TOP_10_2025
    ]


def upsert(docs: list[dict[str, Any]], llm: GeminiAdapter) -> None:
    coll = get_collection()
    log.info("upserting %d documents into '%s'", len(docs), KB_COLLECTION)
    for batch in _chunked(docs, INGEST_BATCH):
        embeddings: list[list[float]] = []
        for sub in _chunked(batch, EMBED_BATCH):
            texts = [d["text"] for d in sub]
            embeddings.extend(embed_with_retry(llm, texts))
            time.sleep(INTER_BATCH_SLEEP)
        coll.upsert(
            ids=[d["id"] for d in batch],
            documents=[d["text"] for d in batch],
            metadatas=[d["metadata"] for d in batch],
            embeddings=embeddings,
        )
        log.info("  +%d", len(batch))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true", help="re-ingest even if KB is populated"
    )
    parser.add_argument("--owasp-only", action="store_true", help="skip MITRE")
    parser.add_argument("--mitre-only", action="store_true", help="skip OWASP")
    args = parser.parse_args()

    coll = get_collection()
    existing = coll.count()
    if existing and not args.force:
        log.info("KB already has %d docs — pass --force to re-ingest", existing)
        return 0

    llm = GeminiAdapter()

    docs: list[dict[str, Any]] = []
    if not args.mitre_only:
        log.info("preparing OWASP Top 10 (%d)", len(OWASP_TOP_10_2025))
        docs.extend(build_owasp_docs())
    if not args.owasp_only:
        stix = fetch_mitre_stix()
        techniques = extract_mitre_techniques(stix)
        log.info("MITRE techniques after de-dupe: %d", len(techniques))
        docs.extend(build_mitre_docs(techniques))

    upsert(docs, llm)

    final = coll.count()
    log.info("done — collection now has %d docs", final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
