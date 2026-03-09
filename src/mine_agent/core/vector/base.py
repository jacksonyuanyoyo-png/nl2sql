"""Vector store abstraction for storing and searching embeddings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple


class VectorStore(ABC):
    """Abstract interface for vector storage and similarity search."""

    @abstractmethod
    def add(
        self,
        namespace: str,
        id: str,
        vector: List[float],
        metadata: Dict[str, Any],
    ) -> None:
        """
        Add a single vector with metadata to a namespace.

        :param namespace: Partition key (e.g. source_id).
        :param id: Unique id for this item within the namespace.
        :param vector: Embedding vector.
        :param metadata: Arbitrary metadata to return on search.
        """
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        namespace: str,
        vector: List[float],
        top_k: int,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Search for nearest neighbors by vector.

        :param namespace: Partition to search in.
        :param vector: Query vector.
        :param top_k: Maximum number of results.
        :return: List of (id, metadata) ordered by similarity (best first).
        """
        raise NotImplementedError

    def search_with_score(
        self,
        namespace: str,
        vector: List[float],
        top_k: int,
    ) -> List[Tuple[str, Dict[str, Any], float]]:
        """
        Search for nearest neighbors by vector, returning similarity scores.

        :param namespace: Partition to search in.
        :param vector: Query vector.
        :param top_k: Maximum number of results.
        :return: List of (id, metadata, score) ordered by similarity (best first).
        """
        results = self.search(namespace, vector, top_k)
        return [(cid, meta, 1.0) for cid, meta in results]

    def delete_namespace(self, namespace: str) -> None:
        """Remove all vectors in a namespace. Optional override."""
        raise NotImplementedError
