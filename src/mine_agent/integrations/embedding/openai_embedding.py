"""OpenAI embedding via OpenAI API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mine_agent.core.embedding.base import EmbeddingService


# Common dimensions
OPENAI_SMALL_DIM = 1536   # text-embedding-3-small
OPENAI_LARGE_DIM = 3072   # text-embedding-3-large


class OpenAIEmbeddingService(EmbeddingService):
    """Embedding using OpenAI embeddings API."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "openai package is required for OpenAI embedding. Install with: pip install openai"
            ) from e

        self.model = model or "text-embedding-3-small"
        client_kwargs: Dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        response = self._client.embeddings.create(
            model=self.model,
            input=texts,
            encoding_format="float",
        )
        by_index = {item.index: item.embedding for item in response.data}
        return [by_index[i] for i in range(len(texts))]

    @property
    def dimension(self) -> int:
        if "large" in self.model.lower():
            return OPENAI_LARGE_DIM
        return OPENAI_SMALL_DIM
