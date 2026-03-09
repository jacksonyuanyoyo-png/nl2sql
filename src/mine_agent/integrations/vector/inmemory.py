"""In-memory vector store using cosine similarity."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from mine_agent.core.vector.base import VectorStore


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore(VectorStore):
    """In-memory vector store. Vectors are stored per namespace; search is brute-force cosine similarity."""

    def __init__(self) -> None:
        # namespace -> id -> (vector, metadata)
        self._store: Dict[str, Dict[str, Tuple[List[float], Dict[str, Any]]]] = {}

    def add(
        self,
        namespace: str,
        id: str,
        vector: List[float],
        metadata: Dict[str, Any],
    ) -> None:
        if namespace not in self._store:
            self._store[namespace] = {}
        self._store[namespace][id] = (list(vector), dict(metadata))

    def search(
        self,
        namespace: str,
        vector: List[float],
        top_k: int,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        scored = self.search_with_score(namespace, vector, top_k)
        return [(cid, meta) for cid, meta, _ in scored]

    def search_with_score(
        self,
        namespace: str,
        vector: List[float],
        top_k: int,
    ) -> List[Tuple[str, Dict[str, Any], float]]:
        if namespace not in self._store or not vector:
            return []

        items = [
            (vid, _cosine_similarity(vector, vec), meta)
            for vid, (vec, meta) in self._store[namespace].items()
        ]
        items.sort(key=lambda x: x[1], reverse=True)
        return [(vid, meta, score) for vid, score, meta in items[:top_k]]

    def delete_namespace(self, namespace: str) -> None:
        if namespace in self._store:
            del self._store[namespace]
