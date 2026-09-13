"""Handbook search: chunk markdown by heading, embed locally with fastembed, search with NumPy.

Twelve short documents make about sixty chunks, so a matrix of normalised vectors and one dot
product per query is all the "vector database" this needs.
"""

import json
import sys
from pathlib import Path

import numpy as np

from app import config

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CACHE_DIR = config.ROOT / ".cache" / "fastembed"

_model = None
_index = None


def chunk_markdown(path: Path) -> list[dict]:
    """Split a handbook page into one chunk per `##` section, keeping the page title for context."""
    title, chunks, heading, body = path.stem, [], None, []

    def flush():
        text = " ".join(line.strip() for line in body if line.strip())
        if heading and text:
            chunks.append({"source": path.name, "heading": heading, "text": text, "title": title})

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            heading, body = line[3:].strip(), []
        else:
            body.append(line)
    flush()
    return chunks


def _embedding_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))
    return _model


def embed_passages(chunks: list[dict]) -> np.ndarray:
    texts = [f"{c['title']} - {c['heading']}: {c['text']}" for c in chunks]
    return np.array(list(_embedding_model().passage_embed(texts)), dtype=np.float32)


def embed_query(query: str) -> np.ndarray:
    return np.array(next(iter(_embedding_model().query_embed([query]))), dtype=np.float32)


class VectorStore:
    """Cosine-similarity search over a small in-memory matrix."""

    def __init__(self):
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.items: list[dict] = []

    def add(self, vectors: np.ndarray, items: list[dict]) -> None:
        vectors = np.asarray(vectors, dtype=np.float32)
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        self.vectors = vectors if not self.items else np.vstack([self.vectors, vectors])
        self.items.extend(items)

    def search(self, vector: np.ndarray, k: int = 3) -> list[tuple[float, dict]]:
        if not self.items:
            return []
        vector = vector / np.linalg.norm(vector)
        scores = self.vectors @ vector
        top = np.argsort(-scores)[:k]
        return [(float(scores[i]), self.items[i]) for i in top]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self.vectors)
        (directory / "items.json").write_text(json.dumps(self.items, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "VectorStore":
        store = cls()
        store.vectors = np.load(directory / "vectors.npy")
        store.items = json.loads((directory / "items.json").read_text(encoding="utf-8"))
        return store


def build_index(directory: Path = config.INDEX_DIR) -> VectorStore:
    chunks = [c for path in sorted(config.HANDBOOK_DIR.glob("*.md")) for c in chunk_markdown(path)]
    store = VectorStore()
    store.add(embed_passages(chunks), chunks)
    store.save(directory)
    return store


def load_index() -> VectorStore:
    """The persisted index, built on first use if `make index` has not been run."""
    global _index
    if _index is None:
        if (config.INDEX_DIR / "vectors.npy").exists():
            _index = VectorStore.load(config.INDEX_DIR)
        else:
            _index = build_index()
    return _index


def search_handbook(query: str, k: int = 3) -> list[dict]:
    results = load_index().search(embed_query(query), k)
    return [{"source": item["source"], "heading": item["heading"], "text": item["text"], "score": round(score, 3)}
            for score, item in results]


if __name__ == "__main__":
    if sys.argv[1:] != ["build"]:
        sys.exit("usage: python -m app.retrieval build")
    built = build_index()
    print(f"indexed {len(built.items)} chunks from {config.HANDBOOK_DIR.name}/ into {config.INDEX_DIR}")
