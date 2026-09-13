import numpy as np
import yaml

from app import config, retrieval
from app.retrieval import VectorStore


def test_chunks_follow_headings():
    chunks = retrieval.chunk_markdown(config.HANDBOOK_DIR / "snowflake.md")
    assert [c["heading"] for c in chunks] == ["What it is", "Owner", "Access levels", "Risk tier", "Justification expected"]
    assert all(c["source"] == "snowflake.md" and c["title"] == "Snowflake" for c in chunks)


def test_vector_store_returns_nearest_first():
    store = VectorStore()
    store.add(np.array([[1, 0], [0, 1], [1, 1]]), [{"id": "x"}, {"id": "y"}, {"id": "xy"}])
    ids = [item["id"] for _, item in store.search(np.array([1.0, 0.1]), k=2)]
    assert ids == ["x", "xy"]


def test_vector_store_round_trips_to_disk(tmp_path):
    store = VectorStore()
    store.add(np.array([[3, 4]]), [{"id": "a"}])
    store.save(tmp_path)
    loaded = VectorStore.load(tmp_path)
    assert loaded.items == [{"id": "a"}]
    assert np.allclose(loaded.vectors, [[0.6, 0.8]])


def test_search_returns_three_cited_chunks():
    results = retrieval.search_handbook("Who approves production access?")
    assert len(results) == 3
    assert all({"source", "heading", "text"} <= set(r) for r in results)


def test_retrieval_eval_meets_gate():
    """Phase 3 gate: the expected file is in the top 3 for at least 13 of 15 questions."""
    cases = yaml.safe_load((config.ROOT / "evals" / "retrieval_cases.yaml").read_text(encoding="utf-8"))
    hits = [c for c in cases if c["expected"] in {r["source"] for r in retrieval.search_handbook(c["question"])}]
    misses = [c["question"] for c in cases if c not in hits]
    assert len(hits) >= 13, f"{len(hits)}/15, missed: {misses}"
