import os
from typing import Optional, Iterable

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "").strip()
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "hs-trends-conversations").strip()
PINECONE_ENV = os.getenv("PINECONE_ENV", "us-east-1").strip()

try:
    from pinecone import Pinecone
except Exception:  # pragma: no cover
    Pinecone = None

_client = None
_index = None


def is_enabled() -> bool:
    return bool(PINECONE_API_KEY) and Pinecone is not None


def get_index():
    global _client, _index
    if not is_enabled():
        return None
    if _client is None:
        _client = Pinecone(api_key=PINECONE_API_KEY)
    if _index is None:
        _index = _client.Index(PINECONE_INDEX)
    return _index


def upsert_vectors(items: Iterable[dict]):
    """items: list of {id: str, values: [float], metadata: dict}"""
    idx = get_index()
    if not idx:
        return {"ok": False, "error": "pinecone disabled"}
    # Pinecone client handles batching internally if list is big
    idx.upsert(vectors=list(items))
    return {"ok": True}


def search(query: list[float], top_k: int = 10, filter: Optional[dict] = None):
    idx = get_index()
    if not idx:
        return {"ok": False, "matches": []}
    r = idx.query(vector=query, top_k=top_k, include_metadata=True, filter=filter)
    return {"ok": True, "matches": r.get("matches", [])}
