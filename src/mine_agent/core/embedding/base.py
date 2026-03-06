"""Embedding service abstraction for multi-vendor vectorization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class EmbeddingService(ABC):
    """Abstract interface for text embedding. Implementations may call DeepSeek, OpenAI, etc."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts into vectors.

        :param texts: List of input strings.
        :return: List of vectors, same length as texts. Each vector is a list of floats.
        """
        raise NotImplementedError

    @property
    def dimension(self) -> int:
        """Return the embedding dimension. Override if known."""
        return 0
