"""Unit tests for embedding services and vector store."""

from __future__ import annotations

import pytest

from mine_agent.integrations.vector.inmemory import InMemoryVectorStore


def test_in_memory_vector_store_add_and_search() -> None:
    store = InMemoryVectorStore()
    store.add("ns1", "id1", [1.0, 0.0, 0.0], {"name": "a"})
    store.add("ns1", "id2", [0.0, 1.0, 0.0], {"name": "b"})
    store.add("ns1", "id3", [0.9, 0.1, 0.0], {"name": "c"})
    results = store.search("ns1", [1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    ids = [r[0] for r in results]
    assert "id1" in ids
    assert "id3" in ids
    assert results[0][0] == "id1"


def test_in_memory_vector_store_empty_namespace() -> None:
    store = InMemoryVectorStore()
    results = store.search("empty_ns", [1.0, 0.0], top_k=5)
    assert results == []


def test_in_memory_vector_store_delete_namespace() -> None:
    store = InMemoryVectorStore()
    store.add("ns1", "id1", [1.0, 0.0], {})
    store.delete_namespace("ns1")
    results = store.search("ns1", [1.0, 0.0], top_k=5)
    assert results == []


def test_in_memory_vector_store_top_k() -> None:
    store = InMemoryVectorStore()
    for i in range(5):
        store.add("ns1", f"id{i}", [float(i), 0.0, 0.0], {})
    results = store.search("ns1", [2.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
