"""RAG retrieval over the ChromaDB knowledge base.

The ingestion script (`scripts.ingest_kb`) populates a single collection
called ``kb`` with two document families:
  - MITRE ATT&CK techniques (metadata.source = "mitre")
  - OWASP Top 10 categories (metadata.source = "owasp")

The retriever embeds the query with the configured Gemini embedding model
and asks Chroma for the top-k matches. Returned documents are *untrusted*
data — never feed them to the LLM as instructions; the chat service wraps
them in BEGIN/END_UNTRUSTED_KB delimiters before sending.
"""
from __future__ import annotations

from dataclasses import dataclass

import chromadb

from app.config import get_settings
from app.services.llm import LLMAdapter, LLMError, LLMProviderError, get_llm

KB_COLLECTION = "soc_kb"


@dataclass(frozen=True)
class KBDoc:
    id: str
    text: str
    source: str  # "mitre" | "owasp"
    name: str
    score: float | None = None


_client: chromadb.api.ClientAPI | None = None


def _get_client() -> chromadb.api.ClientAPI:
    global _client
    if _client is None:
        s = get_settings()
        _client = chromadb.HttpClient(host=s.chroma_host, port=s.chroma_port)
    return _client


def get_collection():
    return _get_client().get_or_create_collection(KB_COLLECTION)


class Retriever:
    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or get_llm()

    def retrieve(self, query: str, k: int = 5) -> list[KBDoc]:
        if not query or not query.strip():
            return []
        coll = get_collection()
        if coll.count() == 0:
            return []
        try:
            embedding = self._llm.embed([query])[0]
        except LLMError:
            # Bubble up; the router maps LLMProviderError to a generic 502.
            raise
        result = coll.query(query_embeddings=[embedding], n_results=k)
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0]
        out: list[KBDoc] = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            out.append(
                KBDoc(
                    id=ids[i],
                    text=doc,
                    source=meta.get("source", "unknown"),
                    name=meta.get("name", ""),
                    score=dists[i] if i < len(dists) else None,
                )
            )
        return out


def kb_status() -> dict[str, int | str]:
    """Return basic KB diagnostics for the /api/kb/status endpoint."""
    try:
        coll = get_collection()
    except Exception as exc:  # pragma: no cover — defensive
        raise LLMProviderError(f"chroma unreachable: {exc}") from exc
    total = coll.count()
    by_source: dict[str, int] = {"mitre": 0, "owasp": 0, "unknown": 0}
    if total:
        # Fetch all metadatas (cheap up to a few thousand docs).
        page = coll.get(include=["metadatas"], limit=10_000)
        for meta in page.get("metadatas") or []:
            src = (meta or {}).get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
    return {"total": total, **by_source}
