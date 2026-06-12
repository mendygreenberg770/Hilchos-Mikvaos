"""Optional semantic search via Voyage AI embeddings.

Disabled (returns nothing) when VOYAGE_API_KEY is unset, so the system works
out of the box with reference detection + FTS5 alone.
"""

import struct

from . import config


def enabled() -> bool:
    return bool(config.VOYAGE_API_KEY)


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a batch of texts. input_type: 'document' for the library, 'query' for questions."""
    if not enabled():
        raise RuntimeError("VOYAGE_API_KEY is not set")
    import httpx
    resp = httpx.post(
        config.VOYAGE_URL,
        headers={"Authorization": f"Bearer {config.VOYAGE_API_KEY}"},
        json={"model": config.VOYAGE_MODEL, "input": texts, "input_type": input_type},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def from_blob(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))
