"""DeepSeek embedding via OpenAI-compatible embeddings API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mine_agent.core.embedding.base import EmbeddingService


# Default dimension for deepseek-embedding (typically 1536 or 1024)
DEEPSEEK_EMBED_BASE_DIM = 1536
DEEPSEEK_EMBED_SMALL_DIM = 768
DEEPSEEK_EMBED_LARGE_DIM = 3072


class DeepSeekEmbeddingService(EmbeddingService):
    """Embedding using DeepSeek API (OpenAI-compatible embeddings endpoint)."""

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
                "openai package is required for DeepSeek embedding. Install with: pip install openai"
            ) from e

        self.model = model or "deepseek-embedding"
        api_key = api_key
        base_url = base_url or "https://api.deepseek.com/v1"

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
        # Preserve order by index
        by_index = {item.index: item.embedding for item in response.data}
        return [by_index[i] for i in range(len(texts))]

    @property
    def dimension(self) -> int:
        if "small" in (self.model or "").lower():
            return DEEPSEEK_EMBED_SMALL_DIM
        if "large" in (self.model or "").lower():
            return DEEPSEEK_EMBED_LARGE_DIM
        return DEEPSEEK_EMBED_BASE_DIM
